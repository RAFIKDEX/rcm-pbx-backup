import re

with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

table_fix = """
/* Table Background Fix */
.fm-table, .table, .cdr-table,
.fm-table tbody, .table tbody, .cdr-table tbody,
.fm-table td, .table td, .cdr-table td,
.fm-table th, .table th, .cdr-table th {
    background: transparent !important;
}
"""

css = re.sub(r'/\* Table Background Fix \*/.*?(?=/\* Table Rows \*/)', table_fix, css, flags=re.DOTALL)

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)
