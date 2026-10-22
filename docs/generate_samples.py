"""Generate README images from an original synthetic document and real outputs."""
import argparse
import json
import sys
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from layoutpdf.contracts import require,write
from layoutpdf.extract import prepare
from layoutpdf.pipeline import build,merge


TRANSLATIONS={
    "Readable PDF Translation":"可读的 PDF 翻译",
    "1. Reading Flow":"1. 阅读节奏",
    "This example":"本示例展示可读的保留排版翻译：页面尺寸、正文栏与固定表格保持一致，中文段落在可用区域内重新换行。标题留白与正文行距共同分配空间，避免译文挤在原段落顶部。",
    "The value":"数值{math}控制模型响应，保留原始上下标。",
    "The ratio":"比值{math}保留在句内，沿用原始分数线。",
    "2. Mathematics and Tables":"2. 公式与表格",
    "Equations remain":"展示公式保留在原有位置，正文在两侧分别排版。行内数学与正文共用基线；表格中的方法名和数值整体保留，以免重排时破坏数据之间的对应关系。",
    "where the variable":"其中，该变量表示归一化处理后的测量值。下方表格中的方法名称和数值均与源文保持一致。",
    "Table 1:":"表 1：保留单元格内容的合成数据表。",
    "3. Search and Copy":"3. 搜索与复制",
    "Search and copy":"搜索与复制应对应可见文字。短段落只出现一次，选区与印出的文字重合。公式裁片不得夹带隐藏的整页原文。",
}


def make_source(path):
    with fitz.open() as pdf:
        page=pdf.new_page(width=420,height=620)
        def line(x,y,text,size=10,font="tiro"):
            page.insert_text((x,y),text,fontsize=size,fontname=font)
        def paragraph(text,y,size=10):
            words=text.split();current=""
            for word in words:
                candidate=(current+" "+word).strip()
                if current and fitz.get_text_length(candidate,fontname="tiro",fontsize=size)>332:
                    line(44,y,current,size);y+=12
                    current=word
                else:current=candidate
            if current:line(44,y,current,size)
        line(44,38,"Readable PDF Translation",17,"tibo")
        line(44,78,"1. Reading Flow",12,"tibo")
        paragraph("This example shows readable layout-preserving translation. Page dimensions, text columns and fixed tables stay intact while Chinese paragraphs wrap within their available regions. Space is shared between heading gaps and body leading, rather than packing the translation at the top of each original paragraph box.",102)
        line(44,174,"The value")
        line(88,174,"x",10,"tiit");line(93,177,"i",6,"tiit");line(93,168,"2",6)
        line(103,174,"controls the model response with its original scripts.")
        line(44,207,"The ratio")
        line(91,202,"1",6);line(91,211,"n",6,"tiit")
        page.draw_line((89,204),(97,204),width=.5)
        line(103,207,"remains in the sentence with its original fraction bar.")
        line(44,242,"2. Mathematics and Tables",12,"tibo")
        paragraph("Equations remain at their source positions, with prose flowing separately on either side. Inline mathematics shares the prose baseline. Method names and numerical values in tables are retained together so that their relationships survive the translation.",266)
        line(160,326,"x",11,"tiit");line(166,320,"2",7);line(175,326,"= 1",11);line(365,326,"(1)")
        paragraph("where the variable denotes a normalized measurement. The following table preserves method names and numerical values exactly as in the source.",354)
        line(44,391,"Table 1: Synthetic data with source cells retained.",9)
        for y in (404,424,444,464):page.draw_line((44,y),(376,y),width=.45)
        for x in (44,224,376):page.draw_line((x,404),(x,464),width=.45)
        for y,a,b in [(418,"Method","Accuracy"),(438,"Baseline","74.2"),(458,"Proposed","81.5")]:
            line(54,y,a,9);line(238,y,b,9)
        line(44,497,"3. Search and Copy",12,"tibo")
        paragraph("Search and copy should operate on visible text. A short paragraph must appear exactly once, and its selection bounds should match the printed words. Formula clips must not carry invisible copies of the source page.",522)
        line(207,601,"1",9)
        pdf.save(path,garbage=4,deflate=True,no_new_id=True)


def translate(document):
    result={}
    missing=[prefix for prefix in TRANSLATIONS
             if not any(p["source"].startswith(prefix) for p in document["paragraphs"])]
    if missing:raise ValueError(f"Missing sample paragraphs: {missing}")
    for p in document["paragraphs"]:
        matches=[t for prefix,t in TRANSLATIONS.items() if p["source"].startswith(prefix)]
        if len(matches)!=1:raise ValueError(f"Unexpected paragraph: {p['source']}")
        tokens=[token for token,entry in p["tokens"].items() if entry["kind"]=="math"]
        result[p["id"]]=matches[0].format(math="".join(tokens))
    return result


def render_details(page,path):
    panels=[]
    font=ImageFont.load_default(size=22)
    hits=page.search_for("短段落")
    if len(hits)!=1:raise ValueError(f"Expected one literal search hit, got {len(hits)}")
    copied=page.get_textbox(hits[0]+(-1,-1,1,1))
    if "短段落" not in copied:raise ValueError(f"Copy check failed: {copied!r}")
    for title,box,highlight in [
        ("Heading hierarchy and body leading",fitz.Rect(40,60,380,229),False),
        ("Actual PDF search bounds: short paragraph",fitz.Rect(40,480,380,575),True),
    ]:
        pix=page.get_pixmap(matrix=fitz.Matrix(2,2),clip=box,alpha=False)
        im=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
        if highlight:
            overlay=Image.new("RGBA",im.size)
            draw=ImageDraw.Draw(overlay)
            for hit in hits:
                draw.rectangle((hit.x0*2-pix.x,hit.y0*2-pix.y,hit.x1*2-pix.x,hit.y1*2-pix.y),
                               fill=(53,142,209,65),outline=(32,112,176,220),width=2)
            im=Image.alpha_composite(im.convert("RGBA"),overlay).convert("RGB")
        panel=Image.new("RGB",(im.width+32,im.height+56),"white")
        ImageDraw.Draw(panel).text((16,12),title,font=font,fill="#263647")
        panel.paste(im,(16,48));panels.append(panel)
    canvas=Image.new("RGB",(max(p.width for p in panels),sum(p.height for p in panels)+16),"#e7edf1")
    y=0
    for panel in panels:canvas.paste(panel,(0,y));y+=panel.height+16
    canvas.save(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workdir",type=Path,help="New directory for generated PDFs and job data")
    parser.add_argument("--assets-dir",type=Path,default=Path(__file__).parent/"assets")
    parser.add_argument("--font");parser.add_argument("--bold-font")
    args=parser.parse_args()
    root=args.workdir.resolve();root.mkdir(parents=True,exist_ok=False)
    make_source(root/"source.pdf")
    doc=prepare(root/"source.pdf",root/"job",regular=args.font,bold=args.bold_font)
    write(root/"translations.json",translate(doc));merge(root/"job",root/"translations.json")
    result=build(root/"job");require(result["diagnostics"])
    if not result["ok"]:raise ValueError("Sample build failed")
    build_dir=Path(result["build"])
    args.assets_dir.mkdir(parents=True,exist_ok=True)
    with fitz.open(build_dir/"bilingual.pdf") as pdf:
        pdf[0].get_pixmap(dpi=144,alpha=False).save(args.assets_dir/"synthetic-bilingual.png")
    with fitz.open(build_dir/"translated.pdf") as pdf:
        render_details(pdf[0],args.assets_dir/"synthetic-details.png")
    print(json.dumps(dict(ok=True,build=str(build_dir),
        images=[str(args.assets_dir/name) for name in ("synthetic-bilingual.png","synthetic-details.png")],
        formula_checks=len(result["formulas"]),selection_pages=len(result["selection_checks"]),
        search_hits=1,paragraphs=len(doc["paragraphs"])),indent=2))


if __name__=="__main__":main()
