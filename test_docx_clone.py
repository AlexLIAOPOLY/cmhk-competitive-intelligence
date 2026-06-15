from docx import Document
import copy

def cloned_paragraph_after(paragraph):
    new_p = copy.deepcopy(paragraph._p)
    paragraph._p.addnext(new_p)
    return type(paragraph)(new_p, paragraph._parent)

doc = Document("carrier_performance_template.docx")
body_slots = [p for p in doc.paragraphs[4:] if p.text.strip()]

start = 0  # Assuming 中国移动 is at index 0
end = 8    # Assuming next company is at index 8

base_slot = body_slots[start + 1]
print("Base slot text:", base_slot.text)

new_slots = [base_slot]
for i in range(4):
    new_slots.append(cloned_paragraph_after(new_slots[-1]))

for i, slot in enumerate(new_slots):
    slot.text = f"Test item {i}"

# Remove the rest
for p in body_slots[start + 2 : end]:
    p._element.getparent().remove(p._element)

doc.save("test_out.docx")
