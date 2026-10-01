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
    display = manifest["display"]
    pixels = display["width"] * display["height"] if "width" in display else display["size"] ** 2
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
  std::cout<<",\\\"pixels\\\":";array(fp_pixels(),{pixels});
  std::cout<<",\\\"frames\\\":";array(fp_frames(),c[5]);std::cout<<"}}"<<std::endl;
 }}fp_destroy();
}}
"""


def doom_wrapper(manifest):
    """The DOOM machine: loads the program and WAD through the RTL loader port, and
    services the frame doorbell like tools/doom/tb_doom.cpp (inspection-port frame
    read, FNV-1a hash identical to the ISS, key FIFO pushes, acknowledge)."""
    ports = manifest["ports"]
    inputs = [p for p in ports if p["direction"] == "input"]
    outputs = [p for p in ports if p["direction"] == "output"]
    writes = "\n".join(
        f"model->{p['name']} = values[{i}] & UINT32_C({(1 << p['width']) - 1});"
        for i, p in enumerate(inputs)
    )
    reads = "\n".join(f"outputs[{i}] = model->{p['name']};" for i, p in enumerate(outputs))
    defaults = "\n".join(f"model->{p['name']} = {p['initial']};" for p in inputs)
    display = manifest["display"]
    return f"""// Generated; model state and all per-edge work stay inside this module.
#include "Vmodel.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#endif
static constexpr unsigned WIDTH={display["width"]}, HEIGHT={display["height"]};
static constexpr unsigned HEADER={display["frameHeader"]}, KEY_FIFO=8;
static constexpr uint32_t RAM_SIZE=0x1000000, WAD_HEADER=0xb00000, WAD_DATA=0xb00010;
static constexpr uint32_t WAD_MAGIC=0x21444157, FRAMEBUFFER=0xf10000, PALETTE=0xf20000;
static std::unique_ptr<VerilatedContext> context;
static std::unique_ptr<Vmodel> model;
static std::array<uint32_t,{len(outputs)}> outputs;
static std::vector<uint32_t> pixels(WIDTH*HEIGHT);
static std::array<uint32_t,6> counters;
static std::vector<uint32_t> frames;
static std::vector<double> frameTimes;
static std::deque<uint32_t> keys;
static std::string console, consoleOut;
static uint64_t edges=0, completed=0;
static std::string failure;
static double now() {{
#ifdef __EMSCRIPTEN__
    return emscripten_get_now();
#else
    auto elapsed=std::chrono::steady_clock::now().time_since_epoch();
    return std::chrono::duration<double,std::milli>(elapsed).count();
#endif
}}
static uint64_t counter(uint32_t lo, uint32_t hi) {{ return uint64_t(hi)<<32 | lo; }}
static void cycle() {{
    model->clk=1; ++edges; context->timeInc(1); model->eval();
    model->clk=0; ++edges; context->timeInc(1); model->eval();
}}
static uint32_t peek(uint32_t address) {{
    model->peek_address=address; model->eval(); return model->peek_word;
}}
static std::vector<uint8_t> readFile(const char* path, size_t limit) {{
    FILE* f=std::fopen(path,"rb");
    if (!f) throw std::runtime_error(std::string("missing package file ")+path);
    std::vector<uint8_t> data(limit+1);
    size_t n=std::fread(data.data(),1,data.size(),f);
    std::fclose(f);
    if (n>limit) throw std::runtime_error(std::string("package file too large: ")+path);
    data.resize(n);
    return data;
}}
// Present each non-zero word, then pulse load_enable (the RTL's loader protocol).
static void load() {{
    std::vector<uint8_t> image(RAM_SIZE,0);
    auto program=readFile("/doom.bin",WAD_HEADER);
    auto wad=readFile("/doom1.wad",FRAMEBUFFER-WAD_DATA);
    std::copy(program.begin(),program.end(),image.begin());
    std::copy(wad.begin(),wad.end(),image.begin()+WAD_DATA);
    uint32_t header[2]={{WAD_MAGIC,uint32_t(wad.size())}};
    std::memcpy(image.data()+WAD_HEADER,header,sizeof header);
    const uint32_t* words=reinterpret_cast<const uint32_t*>(image.data());
    for (uint32_t i=0;i<RAM_SIZE/4;++i) if (words[i]) {{
        model->load_address=i*4; model->load_data=words[i]; model->eval();
        model->load_enable=1; model->eval();
        model->load_enable=0; model->eval();
    }}
    model->inspect=1;
    for (uint32_t i=0;i<RAM_SIZE/4;i+=997)
        if (peek(i*4)!=words[i]) throw std::runtime_error("loader verification failed");
    model->inspect=0; model->eval();
}}
// Doorbell: read the frame through the inspection port, record it, push keys, ack.
static void serviceFrame() {{
    std::vector<uint8_t> bytes(WIDTH*HEIGHT+768);
    model->inspect=1;
    for (uint32_t a=0;a<WIDTH*HEIGHT;a+=4) {{
        uint32_t w=peek(FRAMEBUFFER+a);
        std::memcpy(bytes.data()+a,&w,4);
    }}
    for (uint32_t a=0;a<768;a+=4) {{
        uint32_t w=peek(PALETTE+a);
        std::memcpy(bytes.data()+WIDTH*HEIGHT+a,&w,4);
    }}
    model->inspect=0; model->eval();
    uint64_t hash=1469598103934665603ull;
    for (uint8_t b:bytes) hash=(hash^b)*1099511628211ull;
    const uint8_t* palette=bytes.data()+WIDTH*HEIGHT;
    for (unsigned i=0;i<WIDTH*HEIGHT;++i) {{
        const uint8_t* c=palette+bytes[i]*3;
        pixels[i]=uint32_t(c[0])<<16 | uint32_t(c[1])<<8 | c[2];
    }}
    ++completed;
    frameTimes.push_back(now());
    uint32_t record[HEADER]={{uint32_t(completed),uint32_t(edges),uint32_t(edges>>32),
        model->frame_info,uint32_t(hash),uint32_t(hash>>32),
        model->cycle_lo,model->cycle_hi,model->instret_lo,model->instret_hi}};
    frames.insert(frames.end(),record,record+HEADER);  // pixels: latest frame only
    for (unsigned n=0;n<KEY_FIFO && !keys.empty() && !model->key_full;++n) {{
        uint32_t v=keys.front(); keys.pop_front();
        model->key_push=1; model->key_data=((v>>9&1)<<8)|(v&255); cycle();
    }}
    model->key_push=0;
    model->frame_ack=1; cycle();
    model->frame_ack=0; model->eval();
}}
static void settle() {{
    model->eval();
    if (model->fault) {{
        char text[160];
        std::snprintf(text,sizeof text,"hardware fault cause %u at pc %08x (instret %llu)",
            unsigned(model->fault_cause),model->pc,
            (unsigned long long)counter(model->instret_lo,model->instret_hi));
        throw std::runtime_error(text);
    }}
    if (model->done)
        throw std::runtime_error("program exited with code "+std::to_string(model->exit_code));
    if (!model->clk) {{
        if (model->console_write) console.push_back(char(model->console_data));
        if (model->frame_pending) serviceFrame();
    }}
}}
extern "C" {{
int fp_create() {{
    try {{
        model.reset(); context.reset(new VerilatedContext);
        context->randReset(0);
        model.reset(new Vmodel(context.get()));
        edges=completed=0; frames.clear(); frameTimes.clear(); keys.clear();
        console.clear(); failure.clear(); std::fill(pixels.begin(),pixels.end(),0);
        {defaults}
        model->clk=0; model->run=0;
        model->rst=0; model->eval(); model->rst=1; model->eval(); model->rst=0; model->eval();
        load();
        model->run=1; settle();
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
            model->clk=!model->clk; ++edges; ++count;
            context->timeInc(1); settle();
            if ((count&1023)==0 && budgetMs>0 && now()-start>=budgetMs) break;
        }}
        return int(count);
    }} catch (const std::exception& e) {{ failure=e.what(); return -1; }}
}}
// Key events {{0x100 | pressed<<9 | key}} enter the FIFO at the next frame doorbell.
int fp_key(uint32_t value) {{
    if (!(value&0x100) || value>0x3ff) {{ failure="invalid key event"; return -1; }}
    keys.push_back(value); return int(keys.size());
}}
const char* fp_console() {{ consoleOut.swap(console); console.clear(); return consoleOut.c_str(); }}
const uint32_t* fp_snapshot() {{
    if (!model) return nullptr;
    {reads}
    counters={{uint32_t(edges),uint32_t(edges>>32),uint32_t(model->clk),
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
