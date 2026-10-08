import importlib.util
from pathlib import Path

def test_numeric_performance_comparison_rejects_zero_p_and_count_changes():
    spec=importlib.util.spec_from_file_location('comparison',Path(__file__).resolve().parents[1]/'scripts/compare_performance.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.differences(1.4e-25,0.0,'experiment.p_value','p_value')
    assert module.differences(6000,6001,'experiment.sample_size','sample_size')
    assert module.differences(1.0,1.01,'ratio','ratio')
    assert not module.differences(1.0,1.0+1e-13,'ratio','ratio')
    assert module.differences({'evidence':['a']},{'evidence':[]})
