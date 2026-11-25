"""Shared Lua runtime loading; mandatory in CI, optional on local hosts."""
import ctypes
from ctypes.util import find_library
import os


def load_lua(test):
    library = find_library("lua5.4") or find_library("lua5.3")
    if not library:
        message = "Lua 5.4/5.3 shared library unavailable"
        if os.environ.get("COMPUTER_HOST_REQUIRE_LUA") == "1" or os.environ.get("CI", "").lower() == "true":
            test.fail(message)
        test.skipTest(message)
    return ctypes.CDLL(library)
