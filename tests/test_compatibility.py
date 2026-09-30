import hashlib

import pytest

from cv_gen.generator import GenerationOptions, generate_csv
from cv_gen.tests_catalog import find_test

# Captured from the final C implementation before the Python rewrite.
LEGACY_SHA256 = {
    ("cla4", 0, 0, 0): "195bfa5f6de591df8ab750290c4dc98920416bb9cbd5f7bb0641dfd7efe1eaaf",
    ("cla4", 1, 0, 0): "6a5bccbfa61f76fa35958c569c073e53966946ed180bbe215a28670566033e4f",
    ("cla4", 37, 25, 42): "b1d33e5529e6a7c82a600da6be51a162907c66f5348a42d1d72ddf09329b3a92",
    ("cla4", 100, 512, 18_446_744_073_709_551_615): (
        "cc68565e60d7afb339e17a5ba6156fccce9154a8eeb0f7f23d6c6cd8c7d260ab"
    ),
    ("cla16", 0, 0, 0): "4e48397112634f50e36d21d73109a1e9f22f9b3fff72163c301a5239870bc0da",
    ("cla16", 1, 0, 1): "e769c6493d301e8f9257e54f9bac6bd0e1cac24cf50e6a3d912cec5954a3eadc",
    ("cla16", 73, 97, 42): "aa8adc07257f065b83356789547700bb85382b45ccf3a9cd392df0c644f79965",
    ("cla16", 100, 75, 18_446_744_073_709_551_615): (
        "4e8d8609b323940eaf8b970939cbf2d24e563b46b01985f844472b499324241e"
    ),
}


@pytest.mark.parametrize("parameters, expected", LEGACY_SHA256.items())
def test_csv_is_byte_compatible_with_legacy_c_generator(parameters, expected):
    name, intensity, max_cases, seed = parameters
    test = find_test(name)
    assert test is not None

    csv, _ = generate_csv(test, GenerationOptions(intensity, max_cases, seed))

    assert hashlib.sha256(csv.encode()).hexdigest() == expected
