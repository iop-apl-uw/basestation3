import dataclasses
import typing


@dataclasses.dataclass
class options_t:
    """Data that drives options processing"""

    default_val: typing.Any
    group: set
    args: tuple
    var_type: typing.Any
    kwargs: dict

    def __post_init__(self):
        """Type conversions"""
        if not isinstance(self.args, tuple):
            raise ValueError("args is not a tuple")
        if self.group is not None and not isinstance(self.group, set):
            self.group = set(self.group)
        if not isinstance(self.kwargs, dict):
            raise ValueError("kwargs is not a dict")
