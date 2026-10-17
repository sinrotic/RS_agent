"""有标题证据的类目修正与属性提取；不推断兼容性、性能或人口属性。"""

import copy
import re


CURATION_VERSION = "title-grounded-category-and-traits/1"

# 这里的路径是冻结评测目录的规范路径，不冒充原始平台的分类结果。
PATHS = {
    "Heart Rate Monitors": ["Sports & Outdoors", "Exercise & Fitness", "Heart Rate Monitors"],
    "Wi-Fi Range Extenders": [
        "Electronics",
        "Computers & Accessories",
        "Networking Products",
        "Wi-Fi Range Extenders",
    ],
    "Open-Ear Headphones": [
        "Electronics",
        "Headphones, Earbuds & Accessories",
        "Open-Ear Headphones",
    ],
    "Pen Refills": [
        "Office Products",
        "Office & School Supplies",
        "Writing & Correction Supplies",
        "Pens & Refills",
        "Pen Refills",
    ],
    "Micro SD Memory Cards": [
        "Electronics",
        "Computers & Accessories",
        "Data Storage",
        "Memory Cards",
        "Micro SD Memory Cards",
    ],
    "CB Radio Microphones": [
        "Electronics",
        "Portable Audio & Video",
        "CB Radio Accessories",
        "CB Radio Microphones",
    ],
    "SWR Meters": ["Electronics", "Portable Audio & Video", "CB Radio Accessories", "SWR Meters"],
    "Sticky Note Dispensers": [
        "Office Products",
        "Office & School Supplies",
        "Desk Accessories",
        "Sticky Note Dispensers",
    ],
    "Keyboards": [
        "Electronics",
        "Computers & Accessories",
        "Computer Accessories & Peripherals",
        "Keyboards, Mice & Accessories",
        "Keyboards",
    ],
}


def corrected_category(item):
    """仅纠正已定位的互斥商品类型；不把缺关键词当作错标证据。"""
    title, category = item.get("title", "").lower(), item.get("category")
    if category == "Portable Bluetooth Speakers" and "heart rate monitor" in title:
        return "Heart Rate Monitors", "标题明确为胸带心率计，不是音箱"
    if category == "Earbud Headphones":
        if "wifi extender" in title or "wi-fi extender" in title:
            return "Wi-Fi Range Extenders", "标题明确为 Wi-Fi 信号扩展器，不是耳机"
        if re.search(r"open[ -]ear|bone conduction|bone conducting|air conduction", title):
            return "Open-Ear Headphones", "标题明确为开放式/骨传导/空气传导，不属于入耳式"
    if category in {"Gel Ink Rollerball Pens", "Ballpoint Pens"} and re.search(
        r"\bpen refill\b|\bpen refills\b", title
    ):
        return "Pen Refills", "标题明确为替换笔芯，不是整支笔"
    if category == "Dome Cameras" and re.search(r"micro\s*sdxc|micro\s*sd.*memory card", title):
        return "Micro SD Memory Cards", "标题明确为 micro SD 存储卡，不是摄像头"
    if category == "Fixed-mount CB Radios":
        if "swr meter" in title:
            return "SWR Meters", "标题明确为驻波比测量表，不是车载电台"
        if "microphone" in title and "cb radio," not in title:
            return "CB Radio Microphones", "标题明确为 CB 麦克风配件，不是电台主机"
    if category == "Self-Stick Notes" and "notes dispenser" in title:
        return "Sticky Note Dispensers", "标题明确为便利贴分配器，不是便利贴纸"
    if category == "Keyboard & Mouse Combos" and "touchpad" in title and "mouse" not in title:
        return "Keyboards", "标题是带触摸板的键盘，没有独立鼠标套装证据"
    return None


def title_traits(item):
    """属性只从明确文字提取；未提及、互相矛盾的文字保持未知。"""
    category, title = item.get("category"), item.get("title", "").lower()
    traits = {}
    if category in {"Earbud Headphones", "Over-Ear Headphones", "Open-Ear Headphones"}:
        wireless = bool(re.search(r"\bbluetooth\b|\bwireless\b|\btws\b", title))
        wired = bool(re.search(r"\bwired\b|3\.5\s*mm|\blightning\b|\bmmcx\b|\bcable\b", title))
        if wireless != wired:
            traits["connection_type"] = "wireless" if wireless else "wired"
    if category == "Gel Ink Rollerball Pens":
        values = set(re.findall(r"\b([0-9]\.[0-9])\s*mm\b", title))
        if len(values) == 1:
            traits["tip_mm"] = values.pop()
    return traits


def curate_item(item):
    corrected = copy.deepcopy(item)
    change = corrected_category(corrected)
    if change:
        category, reason = change
        corrected["category_correction"] = {
            "version": CURATION_VERSION,
            "original_category": item["category"],
            "original_path": copy.deepcopy(item.get("category_path", [])),
            "reason": reason,
            "evidence": item["title"],
            "scope": "benchmark_only; not_source_database_write",
        }
        corrected.update(category=category, category_path=copy.deepcopy(PATHS[category]))
    corrected.update(title_traits(corrected))
    if title_traits(corrected):
        corrected["trait_evidence"] = {
            "version": CURATION_VERSION,
            "source": "explicit_title_text; not_verified_manufacturer_specification",
            "title": corrected["title"],
            "fields": sorted(title_traits(corrected)),
        }
    return corrected
