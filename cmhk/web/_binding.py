"""Publish bound functions without wrappers or copied application globals."""


def publish(app, function) -> None:
    """Preserve public import/pickle identity and the original call signature."""
    function.__module__ = app.__name__
    function.__qualname__ = function.__name__
    setattr(app, function.__name__, function)
