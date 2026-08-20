import fitz
from pathlib import Path
pdf = Path('attached_assets/jackthread_1787242988746.pdf')
out = Path('.agents/outputs/jackthread-pages')
out.mkdir(parents=True, exist_ok=True)
doc = fitz.open(pdf)
for i, page in enumerate(doc):
    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
    pix.save(out / f'page-{i+1}.png')
print(f'Rendered {doc.page_count} pages to {out}')
