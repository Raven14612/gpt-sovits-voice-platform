"""Human-readable dataset provenance shared by library and result labels."""
from services import dataset_service


def dataset_names():
    return {item.dataset_id: item.display_name for item in dataset_service.list_datasets()}


def source_name(dataset_id, names):
    return names.get(dataset_id) or (f"数据集已缺失 · {dataset_id}" if dataset_id else "来源未记录")
