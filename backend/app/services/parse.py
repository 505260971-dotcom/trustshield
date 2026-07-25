import os
import re
import shutil
import tempfile

from docx import Document

try:
    import openpyxl
except Exception:
    openpyxl = None

import pdfplumber


def _clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def _record(text, source_ref, page=1, source_kind='text'):
    """Normalize extracted text while keeping a stable source anchor for review."""
    text = _clean(text)
    if not text:
        return None
    return {
        'text': text,
        'source_ref': source_ref,
        'source_kind': source_kind,
        'start_page': page,
        'end_page': page,
    }


def _read_docx_records(path):
    document = Document(path)
    records = []
    for index, paragraph in enumerate(document.paragraphs, 1):
        record = _record(paragraph.text, f'正文第{index}段')
        if record:
            records.append(record)

    # Purchase orders often place their legally binding terms in table cells.
    for table_index, table in enumerate(document.tables, 1):
        for row_index, row in enumerate(table.rows, 1):
            seen_cells = set()
            cells = []
            for column_index, cell in enumerate(row.cells, 1):
                # python-docx repeats the same cell object for horizontally merged cells.
                cell_key = id(cell._tc)
                if cell_key in seen_cells:
                    continue
                seen_cells.add(cell_key)
                value = _clean(cell.text)
                if value:
                    cells.append(f'列{column_index}: {value}')
            record = _record(' | '.join(cells), f'表格{table_index}第{row_index}行', source_kind='table')
            if record:
                records.append(record)
    _apply_docx_page_map(path, records)
    return records


def _page_candidates(text):
    """Generate PDF-searchable text from a normalized paragraph or table row."""
    cleaned = re.sub(r'列\d+\s*:\s*', '', text)
    return [item.strip() for item in cleaned.split('|') if len(item.strip()) >= 3]


def _apply_docx_page_map(path, records):
    """Best-effort DOCX -> PDF mapping through local Word on Windows.

    The source anchor remains available when conversion or text matching cannot
    identify a page, so document ingestion never depends on Office automation.
    """
    if os.name != 'nt' or not records:
        return
    temp_dir = tempfile.mkdtemp(prefix='contractguard-docx-pages-')
    pdf_path = os.path.join(temp_dir, 'source.pdf')
    word = document = None
    try:
        import win32com.client
        word = win32com.client.DispatchEx('Word.Application')
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(os.path.abspath(path), ReadOnly=True, AddToRecentFiles=False)
        document.ExportAsFixedFormat(pdf_path, 17)  # wdExportFormatPDF
        document.Close(False)
        document = None
        word.Quit()
        word = None
        if not os.path.exists(pdf_path):
            return
        with pdfplumber.open(pdf_path) as pdf:
            page_texts = [_clean(page.extract_text() or '') for page in pdf.pages]
        for record in records:
            page_number = None
            for candidate in _page_candidates(record['text']):
                probe = candidate[:80]
                for index, page_text in enumerate(page_texts, 1):
                    if probe in page_text or (len(probe) >= 12 and probe[:12] in page_text):
                        page_number = index
                        break
                if page_number:
                    break
            if page_number:
                record['start_page'] = page_number
                record['end_page'] = page_number
                record['source_ref'] = f'第{page_number}页 · {record["source_ref"]}'
    except Exception:
        # Word may be unavailable in a headless deployment; stable anchors still work.
        return
    finally:
        if document is not None:
            try:
                document.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)


def _read_image_records(path):
    """Optional OCR for scanned contract images. Requires pytesseract + system tesseract."""
    try:
        from PIL import Image
        import pytesseract
    except Exception as exc:
        raise ValueError('扫描件 OCR 依赖未安装：请安装 Pillow、pytesseract，并配置系统 Tesseract') from exc
    try:
        text = pytesseract.image_to_string(Image.open(path), lang='chi_sim+eng')
    except Exception as exc:
        raise ValueError(f'OCR 识别失败：{exc}') from exc
    out = []
    for index, line in enumerate((text or '').splitlines(), 1):
        record = _record(line, f'OCR第{index}行', source_kind='ocr')
        if record:
            out.append(record)
    if not out:
        raise ValueError('OCR 未识别到可用文本，请检查图片清晰度或改用 DOCX/PDF')
    return out


def read_paragraphs(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.docx':
        return _read_docx_records(path)
    if ext == '.pdf':
        out = []
        with pdfplumber.open(path) as pdf:
            for page_index, page in enumerate(pdf.pages, 1):
                for line in (page.extract_text() or '').split('\n'):
                    record = _record(line, f'第{page_index}页', page=page_index, source_kind='pdf')
                    if record:
                        out.append(record)
        return out
    if ext in ('.png', '.jpg', '.jpeg', '.webp', '.bmp'):
        return _read_image_records(path)
    if ext == '.txt':
        with open(path, encoding='utf-8') as file:
            return [record for index, line in enumerate(file, 1)
                    if (record := _record(line, f'第{index}行', source_kind='text'))]
    if ext in ('.xlsx', '.xls') and openpyxl:
        out = []
        workbook = openpyxl.load_workbook(path, data_only=True)
        for worksheet in workbook.worksheets:
            for row_index, row in enumerate(worksheet.iter_rows(values_only=True), 1):
                cells = [str(cell) for cell in row if cell is not None]
                record = _record(' | '.join(cells), f'工作表“{worksheet.title}”第{row_index}行', source_kind='sheet')
                if record:
                    out.append(record)
        return out
    raise ValueError(f'不支持的格式: {ext}')


def split_clauses(records, max_len=900):
    clauses = []
    current = None
    num_re = re.compile(
        r'^(第[一二三四五六七八九十百]+条|[一二三四五六七八九十]+、|[0-9]{1,3}[、.\\.]\s|'
        r'[(（][0-9一二三四五六七八九十A-Za-z]+[)）]|Article\s+\d+|Clause\s+\d+)\s*'
    )

    def flush():
        nonlocal current
        if current and current['text'].strip():
            current['text'] = _clean(current['text'])
            if current['text']:
                clauses.append(current)
        current = None

    for record in records:
        text = record['text'].strip()
        if not text:
            continue
        page = record.get('start_page', 1)
        source_ref = record.get('source_ref', '')
        source_kind = record.get('source_kind', 'text')
        if source_kind in {'table', 'sheet'} or num_re.match(text):
            flush()
            current = {
                'text': text,
                'start_page': page,
                'end_page': page,
                'source_ref': source_ref,
            }
            continue
        if current is None:
            current = {
                'text': text,
                'start_page': page,
                'end_page': page,
                'source_ref': source_ref,
            }
        else:
            current['text'] += ' ' + text
            current['end_page'] = page
            if source_ref and source_ref not in current.get('source_ref', ''):
                refs = current.get('source_ref', '').split('；') if current.get('source_ref') else []
                if len(refs) < 5:
                    refs.append(source_ref)
                elif refs[-1] != '等':
                    refs.append('等')
                current['source_ref'] = '；'.join(refs)
            if len(current['text']) > max_len * 2:
                flush()
    flush()

    out = []
    for clause in clauses:
        segments = [clause['text']]
        if len(clause['text']) > max_len:
            segments = []
            buffer = ''
            for segment in re.split(r'(?<=[。；;])', clause['text']):
                if len(buffer) + len(segment) <= max_len:
                    buffer += segment
                else:
                    if buffer.strip():
                        segments.append(_clean(buffer))
                    buffer = segment
            if buffer.strip():
                segments.append(_clean(buffer))
        for text in segments:
            out.append({
                'id': f'C{len(out) + 1}',
                'text': text,
                'start_page': clause['start_page'],
                'end_page': clause['end_page'],
                'source_ref': clause.get('source_ref', ''),
            })
    return out


def parse_contract(path):
    records = read_paragraphs(path)
    clauses = split_clauses(records)
    full = '\n'.join(record['text'] for record in records)
    return {'clauses': clauses, 'full_text': full, 'n_clauses': len(clauses)}
