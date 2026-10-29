"""Robot-independent, explicitly targeted command data. Never executable source."""
from typing import Literal
from pydantic import Field, StrictFloat, model_validator
from shared.models.contract import Contract


class StandardCommand(Contract):
    type: Literal['SET_ACTUATOR','SET_COMPONENT','MOVE_END_EFFECTOR']
    target: str = Field(min_length=1,max_length=120)
    value: StrictFloat | None = None
    unit: Literal['rad','m','percent'] | None = None
    position: list[StrictFloat] | None = Field(default=None,min_length=3,max_length=3)
    orientation_rpy: list[StrictFloat] | None = Field(default=None,min_length=3,max_length=3)
    position_unit: Literal['m'] | None = None
    orientation_unit: Literal['rad'] | None = None
    frame: str | None = None

    @model_validator(mode='after')
    def shape(self):
        if self.type=='MOVE_END_EFFECTOR':
            if self.value is not None or self.unit is not None or self.position is None or self.position_unit!='m' or not self.frame:
                raise ValueError('Pose tasks require position, position_unit=m and an explicit configured frame; no scalar value/unit')
            if (self.orientation_rpy is None) != (self.orientation_unit is None) or self.orientation_rpy is not None and self.orientation_unit!='rad':
                raise ValueError('Orientation requires RPY and orientation_unit=rad together')
        elif self.value is None or self.unit is None or any(v is not None for v in (self.position,self.orientation_rpy,self.position_unit,self.orientation_unit,self.frame)):
            raise ValueError('Direct tasks require value and unit only')
        return self
