def get_col_letter(n):
    res = ""
    n += 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res = chr(65 + rem) + res
    return res

for i in range(30):
    print(f"{i}: {get_col_letter(i)}")
