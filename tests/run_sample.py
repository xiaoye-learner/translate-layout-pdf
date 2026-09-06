import json
import sys
from pathlib import Path
from test_pipeline import make_fixture, prepare, write, merge, build, review, translate_document

root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
make_fixture(root / "source.pdf")
doc = prepare(root / "source.pdf", root / "job")
write(root / "batch.json", translate_document(doc))
merge(root / "job", root / "batch.json")
result = build(root / "job")
print(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(review(root / "job"), ensure_ascii=False, indent=2))
