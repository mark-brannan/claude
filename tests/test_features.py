"""Binds every scenario under features/ to a test; the steps are in conftest.py."""
from pytest_bdd import scenarios

scenarios("../features")
