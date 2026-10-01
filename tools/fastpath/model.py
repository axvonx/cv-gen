"""Generate the narrow, bulk C ABI around a Verilated hardware model."""


def wrapper(manifest):
    ports = manifest["ports"]
    inputs = [p for p in ports if p["direction"] == "input"]
    outputs = [p for p in ports if p["direction"] == "output"]
    writes = "\n".join(
        f"model->{p['name']} = values[{i}] & UINT32_C({(1 << p['width']) - 1});"
        for i, p in enumerate(inputs)
    )
    reads = "\n".join(f"outputs[{i}] = model->{p['name']};" for i, p in enumerate(outputs))
    defaults = "\n".join(f"model->{p['name']} = {p['initial']};" for p in inputs)
    clock = manifest["clock"]
    size = manifest["display"]["size"]
    if manifest["profile"] == "rv32-graphics":
        observer = """
        if (model->screen_write) {
            unsigned base = model->screen_address & 252;
            for (unsigned lane=0; lane<4; ++lane)
                if (model->screen_mask & (1u<<lane))
                    pixels[base+lane] = ((model->screen_data>>(lane*8))&255)*0x010101;
        }
        if (model->result != previousFrame) {
            if (model->result && model->result != previousFrame+1)
                throw std::runtime_error("nonsequential frame counter");
            if (model->result) recordFrame(model->result-1);
            previousFrame = model->result;
        }
        if (model->fault) throw std::runtime_error("hardware fault");
        """
        boot = (
            "model->run=0; model->rst=1; settle(); model->rst=0; settle(); model->run=1; settle();"
        )
    else:
        row = "\n".join(f"pixels[row*SIZE+{i}] = model->color_{i};" for i in range(size))
        observer = f"""
        unsigned row=model->row_index, frame=model->frame;
        if (row >= SIZE) throw std::runtime_error("invalid scanout row");
        if (row != previousRow || frame != previousFrame) {{
            {row}
            if (row == SIZE-1) recordFrame(frame);
            previousRow=row; previousFrame=frame;
        }}
        """
        boot = "settle();"
    return f"""// Generated; model state and all per-edge work stay inside this module.
#include "Vmodel.h"
#include "verilated.h"
#include <array>
#include <vector>
#include <memory>
#include <stdexcept>
#include <string>
#include <chrono>
#include <cstdint>
#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#endif
static constexpr unsigned SIZE={size};
static std::unique_ptr<VerilatedContext> context;
static std::unique_ptr<Vmodel> model;
static std::array<uint32_t,{len(outputs)}> outputs;
static std::array<uint32_t,SIZE*SIZE> pixels;
static std::array<uint32_t,6> counters;
static std::vector<uint32_t> frames;
static std::vector<double> frameTimes;
static uint64_t edges=0, completed=0;
static uint32_t previousFrame=UINT32_MAX, previousRow=UINT32_MAX;
static std::string failure;
static double now() {{
#ifdef __EMSCRIPTEN__
    return emscripten_get_now();
#else
    auto elapsed=std::chrono::steady_clock::now().time_since_epoch();
    return std::chrono::duration<double,std::milli>(elapsed).count();
#endif
}}
static void recordFrame(uint32_t frame) {{
    ++completed;
    frameTimes.push_back(now());
    frames.push_back(frame);
    frames.push_back(uint32_t(edges));
    frames.push_back(uint32_t(edges>>32));
    frames.insert(frames.end(),pixels.begin(),pixels.end());
}}
static void settle() {{
    model->eval();
    {observer}
}}
extern "C" {{
int fp_create() {{
    try {{
        model.reset(); context.reset(new VerilatedContext);
        context->randReset(0);
        model.reset(new Vmodel(context.get()));
        edges=completed=0; pixels.fill(0); frames.clear(); frameTimes.clear(); failure.clear();
        previousFrame=previousRow=UINT32_MAX;
        {defaults}
        model->{clock}=0;
        {boot}
        frames.clear(); frameTimes.clear();
        return 0;
    }} catch (const std::exception& e) {{ failure=e.what(); return -1; }}
}}
int fp_reset() {{ return fp_create(); }}
int fp_apply_inputs(const uint32_t* values) {{
    if (!model) {{ failure="model not initialized"; return -1; }}
    try {{
        frames.clear(); frameTimes.clear();
        {writes}
        settle(); return 0;
    }} catch (const std::exception& e) {{ failure=e.what(); return -1; }}
}}
int fp_advance(unsigned limit, double budgetMs) {{
    if (!model) {{ failure="model not initialized"; return -1; }}
    try {{
        frames.clear(); frameTimes.clear();
        const double start=now();
        unsigned count=0;
        while (count<limit) {{
            model->{clock}=!model->{clock}; ++edges; ++count;
            context->timeInc(1); settle();
            if ((count&127)==0 && budgetMs>0 && now()-start>=budgetMs) break;
        }}
        return int(count);
    }} catch (const std::exception& e) {{ failure=e.what(); return -1; }}
}}
const uint32_t* fp_snapshot() {{
    if (!model) return nullptr;
    {reads}
    counters={{uint32_t(edges),uint32_t(edges>>32),uint32_t(model->{clock}),
               uint32_t(completed),uint32_t(completed>>32),uint32_t(frames.size())}};
    return counters.data();
}}
const uint32_t* fp_outputs() {{ return outputs.data(); }}
const uint32_t* fp_pixels() {{ return pixels.data(); }}
const uint32_t* fp_frames() {{ return frames.data(); }}
const double* fp_frame_times() {{ return frameTimes.data(); }}
const char* fp_error() {{ return failure.c_str(); }}
void fp_destroy() {{ if (model) model->final(); model.reset(); context.reset(); }}
}}
"""


def native_runner(manifest):
    count = sum(p["direction"] == "input" for p in manifest["ports"])
    outputs = sum(p["direction"] == "output" for p in manifest["ports"])
    size = manifest["display"]["size"]
    return f"""#include <iostream>
#include <cstdint>
#include <string>
extern "C" {{ int fp_create(); int fp_reset(); int fp_apply_inputs(const uint32_t*);
int fp_advance(unsigned,double); const uint32_t* fp_snapshot();
const uint32_t* fp_outputs(); const uint32_t* fp_pixels(); const uint32_t* fp_frames();
const char* fp_error(); void fp_destroy(); }}
void array(const uint32_t* p,unsigned n) {{
 std::cout<<'[';for(unsigned i=0;i<n;++i){{if(i)std::cout<<',';std::cout<<p[i];}}std::cout<<']';
}}
int main() {{
 if(fp_create()<0){{std::cerr<<fp_error();return 1;}}
 std::string op;
 while(std::cin>>op){{
  int result=0;
  if(op=="advance"){{unsigned n;std::cin>>n;result=fp_advance(n,0);}}
  else if(op=="reset")result=fp_reset();
  else if(op=="inputs"){{uint32_t v[{count}];for(auto& x:v)std::cin>>x;result=fp_apply_inputs(v);}}
  else if(op!="snapshot")return 2;
  if(result<0){{std::cerr<<fp_error();return 1;}}
  auto c=fp_snapshot();std::cout<<"{{\\\"counters\\\":";array(c,6);
  std::cout<<",\\\"outputs\\\":";array(fp_outputs(),{outputs});
  std::cout<<",\\\"pixels\\\":";array(fp_pixels(),{size * size});
  std::cout<<",\\\"frames\\\":";array(fp_frames(),c[5]);std::cout<<"}}"<<std::endl;
 }}fp_destroy();
}}
"""
