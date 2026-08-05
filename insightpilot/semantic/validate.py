"""Validate bundled semantic models for local use and CI."""

from __future__ import annotations

import argparse
import json

from insightpilot.semantic.catalog import load_builtin_catalog


def validate_builtin_models() -> dict[str, object]:
    catalog = load_builtin_catalog()
    models = catalog.list_models()
    errors = {model.model_id: model.validate() for model in models}
    errors = {model_id: values for model_id, values in errors.items() if values}
    return {
        "status": "PASS" if not errors else "FAIL",
        "model_count": len(models),
        "model_ids": [model.model_id for model in models],
        "catalog_fingerprint": catalog.fingerprint(),
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="校验内置语义模型。")
    parser.add_argument("--output-format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    result = validate_builtin_models()
    if args.output_format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"语义模型校验={result['status']} 模型数量={result['model_count']} "
            f"目录指纹={result['catalog_fingerprint']}"
        )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
