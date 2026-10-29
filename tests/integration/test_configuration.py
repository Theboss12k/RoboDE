import copy
import shutil
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.api import configuration,storage
from services.validation.registry import MODEL_ROOT,load_model


def test_shared_model_edit_is_validated_and_rolls_back_incompatible_limits(store,tmp_path,monkeypatch):
    root=tmp_path/'registry'
    shutil.copytree(MODEL_ROOT/'demo_arm',root/'demo_arm')
    monkeypatch.setattr(configuration,'MODEL_ROOT',root)
    monkeypatch.setattr(storage,'MODEL_ROOT',root)
    original=load_model(root/'demo_arm')
    actuators=copy.deepcopy(original['actuators']['actuators'])
    actuators['base_yaw']['min']=.5  # Excludes the saved initial value.
    with TestClient(create_app(store)) as client:
        response=client.put('/api/registry/demo_arm/configuration',json={'actuators':actuators,'capabilities':original['capabilities']})
        assert response.status_code==422
        assert load_model(root/'demo_arm')['actuators']==original['actuators']
        actuators['base_yaw']['min']=original['actuators']['actuators']['base_yaw']['min']
        actuators['base_yaw']['velocity']*=.8
        response=client.put('/api/registry/demo_arm/configuration',json={'actuators':actuators,'capabilities':original['capabilities']})
        assert response.status_code==200,response.text
        assert list((store.runtime/'registry_backups').glob('demo_arm/*/actuators.yaml'))
