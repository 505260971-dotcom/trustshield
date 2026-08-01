# -*- coding: utf-8 -*-
"""Word 修订版导出: 将审查报告生成为带风险批注/修改建议的 .docx。
P0 实现: 原文条款 + 红色批注段落 + 建议表（非 OpenXML 原位 TrackChanges，标注清晰可手动采纳）。
"""
import os
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.text import WD_COLOR_INDEX


def _red(run, text, bold=True, size=10):
    run.text = text
    run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    run.font.size = Pt(size)
    run.font.bold = bold
    return run


def _heading(doc, text, level):
    """Customer templates can omit Word's built-in heading styles."""
    try:
        return doc.add_heading(text, level=level)
    except KeyError:
        paragraph = doc.add_paragraph()
        run = paragraph.add_run(text)
        run.bold = True
        run.font.size = Pt(16 if level == 0 else 12)
        return paragraph


def _highlight_evidence(document, evidence):
    needle = (evidence or '').strip()
    if len(needle) < 3:
        return False
    for paragraph in list(document.paragraphs) + [p for table in document.tables for row in table.rows for cell in row.cells for p in cell.paragraphs]:
        if needle in paragraph.text:
            for run in paragraph.runs:
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            return True
    return False


def _add_word_comments(path, risks):
    """Attach comments and native tracked substitutions when Word is available."""
    if os.name != 'nt' or not risks:
        return
    word = document = None
    try:
        import win32com.client
        word = win32com.client.DispatchEx('Word.Application')
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(os.path.abspath(path), ReadOnly=False, AddToRecentFiles=False)
        document.TrackRevisions = True
        for risk in risks:
            evidence = (risk.get('evidence') or '').strip()
            if len(evidence) < 3:
                continue
            search_range = document.Content.Duplicate
            finder = search_range.Find
            finder.ClearFormatting()
            finder.Text = evidence
            finder.Forward = True
            finder.Wrap = 0  # wdFindStop
            if finder.Execute():
                comment = f"ContractGuard {risk.get('rule_id', '')} · {risk.get('level', '')}\r\n建议：{risk.get('suggestion', '请按底线条款修订')}"
                document.Comments.Add(search_range, comment)
                replacement = (risk.get('suggestion') or '').strip()
                # The export route supplies only human-adopted findings. Replacing
                # the cited evidence creates an inspectable Word revision instead
                # of merely a report appendix. Keep the source text when no usable
                # replacement was supplied.
                if replacement and len(replacement) <= 500:
                    search_range.Text = replacement
        document.Save()
        document.Close(False)
        document = None
        word.Quit()
        word = None
    except Exception:
        # Comments are an enhancement; the highlighted source copy remains usable.
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


def export_revised_docx(report, out_path, mode='revised', source_path='', translation=None):
    """Create a source-contract copy; revised mode adds visible risk highlights and a review appendix.

    Modes:
    - revised: risk highlights + appendix + optional Word comments
    - plain: original DOCX copy only (or bare appendix when source missing)
    - bilingual: original clauses with target-language paragraphs inserted after each clause
    """
    translation = translation or {}
    translated_items = {
        item.get('clause_id'): item
        for item in (translation.get('translated') or [])
        if item and item.get('clause_id')
    }
    lang_name = translation.get('target_lang_name') or translation.get('target_lang') or ''

    if source_path and os.path.splitext(source_path)[1].lower() == '.docx' and os.path.exists(source_path):
        doc = Document(source_path)
        if mode == 'plain':
            doc.save(out_path)
            return out_path
    else:
        doc = Document()
        if mode == 'plain':
            # Non-DOCX sources still need a readable plain export.
            _heading(doc, f'合同原文副本 · {report.get("filename", "")}', level=0)
            for clause in report.get('clauses', []) or []:
                p = doc.add_paragraph()
                p.add_run(f'条款 {clause.get("id", "")}').bold = True
                doc.add_paragraph(clause.get('text', ''))
            doc.save(out_path)
            return out_path

    sm = report.get('summary', {}) or {}
    fields = report.get('contract_fields', {}) or {}
    risks = report.get('risks', []) or []
    clauses = report.get('clauses', []) or []

    doc.add_page_break()
    # 审查附录
    title_suffix = f' · 双语对照（{lang_name}）' if mode == 'bilingual' and lang_name else ''
    _heading(doc, f'合同评审报告 · {report.get("filename", "")}{title_suffix}', level=0)
    p = doc.add_paragraph()
    r = p.add_run(f'总体结论：{sm.get("overall_level","—")}    '
                  f'条款 {sm.get("n_clauses",0)} 条    风险 {sm.get("n_risks",0)} 条'
                  f'（高 {sm.get("high",0)} / 中 {sm.get("mid",0)} / 低 {sm.get("low",0)}）    '
                  f'脱敏实体 {report.get("masked_entities",0)} 个')
    r.font.size = Pt(11)
    # 合同字段摘要
    _heading(doc, '一、合同关键字段', level=1)
    fp = doc.add_paragraph()
    parts = [
        f'我方(立场): {fields.get("our_party","—")}',
        f'业务类型: {fields.get("business_type","—")}',
        f'甲方: {(fields.get("parties",{}) or {}).get("甲方","—")}',
        f'乙方: {(fields.get("parties",{}) or {}).get("乙方","—")}',
        f'有效期(年): {fields.get("validity_years","—")}',
        f'交易金额: {fields.get("total_amount","—")} {fields.get("currency","")}',
        f'付款节点: {fields.get("payment_terms","—")}',
    ]
    fp.add_run('  |  '.join(parts)).font.size = Pt(10)

    # 风险清单表
    _heading(doc, '二、风险分级清单', level=1)
    if risks:
        tbl = doc.add_table(rows=1, cols=5)
        try:
            tbl.style = 'Light Grid Accent 1'
        except KeyError:
            pass
        hdr = tbl.rows[0].cells
        for i, t in enumerate(['条款', '等级', '违反底限', '风险证据', '修改建议']):
            hdr[i].text = t
        for x in risks:
            row = tbl.add_row().cells
            row[0].text = str(x.get('clause_id', '-'))
            lv = x.get('level', x.get('severity', ''))
            row[1].text = lv
            if x.get('severity') == 'high':
                for c in row: c.paragraphs[0].runs and c.paragraphs[0].runs[0].font.color.rgb and None
            row[2].text = f"{x.get('rule_id','')} {x.get('rule_baseline','')}"
            row[3].text = x.get('evidence', '—')
            row[4].text = x.get('suggestion', '—')
            if x.get('severity') == 'high':
                for c in row:
                    for para in c.paragraphs:
                        for run in para.runs:
                            run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    else:
        doc.add_paragraph('未命中风险底线。')

    # 条款 + 批注 / 双语
    section_title = '三、合同条款与双语对照' if mode == 'bilingual' else '三、合同条款与修订建议'
    _heading(doc, section_title, level=1)
    risk_by_clause = {}
    for x in risks:
        risk_by_clause.setdefault(x.get('clause_id', '-'), []).append(x)
    for c in clauses:
        cid = c.get('id', '')
        cp = doc.add_paragraph()
        anchor = c.get('source_ref') or f'第 {c.get("start_page","?")} 页'
        cp.add_run(f'条款 {cid}（{anchor}）').bold = True
        doc.add_paragraph(c.get('text', ''))
        if mode == 'bilingual':
            item = translated_items.get(cid) or {}
            translated = (item.get('translated') or '').strip()
            tp = doc.add_paragraph()
            tp.paragraph_format.left_indent = Pt(14)
            run = tp.add_run(f'【译文{("·" + lang_name) if lang_name else ""}】{translated or "（暂无译文，请先完成翻译）"}')
            run.font.color.rgb = RGBColor(0x00, 0x55, 0x99)
            run.font.size = Pt(10)
        if mode in ('revised', 'bilingual') and cid in risk_by_clause:
            for x in risk_by_clause[cid]:
                if mode == 'revised':
                    _highlight_evidence(doc, x.get('evidence', ''))
                ap = doc.add_paragraph()
                ap.paragraph_format.left_indent = Pt(14)
                _red(ap.add_run(''),
                     f'【风险·{x.get("level","")}】违反底限 {x.get("rule_id","")}: {x.get("rule_baseline","")}')
                ap2 = doc.add_paragraph()
                ap2.paragraph_format.left_indent = Pt(14)
                _red(ap2.add_run(''), f'证据: {x.get("evidence","—")}', bold=False)
                ap3 = doc.add_paragraph()
                ap3.paragraph_format.left_indent = Pt(14)
                _red(ap3.add_run(''), f'建议: {x.get("suggestion","—")}', bold=False)
                if x.get('numeric_note'):
                    ap4 = doc.add_paragraph()
                    ap4.paragraph_format.left_indent = Pt(14)
                    _red(ap4.add_run(''), f'数值依据: {x.get("numeric_note")}', bold=False)

    # 审查链路
    if report.get('steps'):
        _heading(doc, '四、Agent 审查步骤与处理记录', level=1)
        for i, st in enumerate(report.get('steps', []), 1):
            doc.add_paragraph(f'{i}. {st}')
    doc.save(out_path)
    if mode == 'revised':
        _add_word_comments(out_path, risks)
    return out_path
