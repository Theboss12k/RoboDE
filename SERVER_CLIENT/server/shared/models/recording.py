"""Bounded camera recording contract. Coordinates use the project's metre, Z-up frame."""
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_VIDEO_BYTES = 256 * 1024 * 1024
ACTIVE_RECORDING = {'recording', 'finalizing'}


class RecordingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    resolution: Literal['640x360', '1280x720', '1920x1080'] = '1280x720'
    fps: Literal[5, 10, 15, 30] = 15
    duration_seconds: int = Field(default=60, ge=1, le=300)
    position: tuple[float, float, float] = (2., 2., 1.5)
    look_at: tuple[float, float, float] = (0., .5, .3)

    @model_validator(mode='after')
    def camera(self):
        if any(abs(x) > 1000 for x in (*self.position, *self.look_at)):
            raise ValueError('Camera coordinates must be within 1000 metres of the world origin')
        if math.dist(self.position, self.look_at) < .01:
            raise ValueError('Camera position and look-at point must be distinct')
        return self
