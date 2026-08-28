from autosub_zh.asr import build_asr_attempts, is_asr_backend_failure


def test_cuda_attempts_include_int8_gpu_fallback_before_cpu() -> None:
    attempts = build_asr_attempts("cuda", "int8_float16", 5)

    assert [(item["device"], item["compute_type"], item["beam_size"]) for item in attempts] == [
        ("cuda", "int8_float16", 5),
        ("cuda", "int8_float16", 1),
        ("cuda", "int8", 1),
        ("cpu", "int8", 1),
    ]


def test_asr_backend_failure_detects_windows_cuda_dll_errors() -> None:
    assert is_asr_backend_failure(RuntimeError("Library cublas64_12.dll is not found or cannot be loaded"))
    assert is_asr_backend_failure(RuntimeError("RuntimeError: CUDA failed with error out of memory"))
