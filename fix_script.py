import json

def fix_val_src(val, src):
    if not val:
        return ""
    if src:
        # cleanup src prefix if it has "SOURCE: "
        if src.startswith("SOURCE: "):
            src = src[8:].strip()
        return f"{val}\n(来源: {src})"
    return str(val)

# Test it
print(repr(fix_val_src("", "http://foo")))
print(repr(fix_val_src("10", "SOURCE: http://foo")))
