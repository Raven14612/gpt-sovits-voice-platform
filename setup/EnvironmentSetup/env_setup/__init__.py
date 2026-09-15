def run_check(*args, **kwargs):
    from .checker import run_check as _run_check
    return _run_check(*args, **kwargs)
