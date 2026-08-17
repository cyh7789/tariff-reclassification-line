import sys
from types import ModuleType
from unittest.mock import Mock


sync_module = ModuleType("fleet.sync")
gate_module = ModuleType("fleet.sync.gate")
gate_module.assert_healthy = Mock()
sync_module.gate = gate_module
sys.modules.setdefault("fleet.sync", sync_module)
sys.modules.setdefault("fleet.sync.gate", gate_module)
