from html import escape


def extract_tables(page):
    # Ignore large background rectangles, which can be mistaken for cell borders.
    ruled_page = page.filter(
        lambda obj: obj["object_type"] != "rect" or obj["width"] <= 1 or obj["height"] <= 1
    )
    tables = []
    for number, table in enumerate(ruled_page.find_tables(), start=1):
        xs = sorted({x for box in table.cells for x in (box[0], box[2])})
        ys = sorted({y for box in table.cells for y in (box[1], box[3])})
        cells = []
        for box in sorted(table.cells, key=lambda b: (b[1], b[0])):
            cells.append({
                "row": ys.index(box[1]),
                "column": xs.index(box[0]),
                "row_span": ys.index(box[3]) - ys.index(box[1]),
                "column_span": xs.index(box[2]) - xs.index(box[0]),
                "bbox": list(box),
                "text": (page.crop(box).extract_text() or "").strip(),
            })
        html = ["<table>"]
        for row in range(len(ys) - 1):
            html.append("<tr>")
            for cell in (c for c in cells if c["row"] == row):
                text = escape(cell["text"]).replace("\n", "<br>")
                html.append(
                    f'<td rowspan="{cell["row_span"]}" colspan="{cell["column_span"]}">{text}</td>'
                )
            html.append("</tr>")
        html.append("</table>")
        tables.append({
            "table_id": f"page-{page.page_number}-table-{number}",
            "page_number": page.page_number,
            "bbox": list(table.bbox),
            "rows": table.extract(),
            "cells": cells,
            "html": "\n".join(html),
            "review_status": "draft",
        })
    return tables


def text_outside_tables(page, tables):
    def outside(obj):
        if obj["object_type"] != "char":
            return True
        x = (obj["x0"] + obj["x1"]) / 2
        y = (obj["top"] + obj["bottom"]) / 2
        return not any(t["bbox"][0] <= x <= t["bbox"][2] and
                       t["bbox"][1] <= y <= t["bbox"][3] for t in tables)

    return (page.filter(outside).extract_text() or "").strip()
