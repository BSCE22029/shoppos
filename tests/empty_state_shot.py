"""One-off visual check: confirms the empty-state message and the POS empty-cart placeholder render."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screenshots as S
S.prepare()
app, out = S.app, S.out

app.navigate("products")
S.pump()
scr = app.screens["products"]
scr.q.set("zzz-nothing-matches-zzz")
scr.table.reload()
S.pump()
S.shot("empty_products")

app.navigate("pos")
S.pump()
S.shot("empty_pos_cart")

app.toggle_theme()
S.pump()
app.navigate("dashboard")
S.pump()
S.shot("dark_dashboard")
app.navigate("pos")
S.pump()
S.shot("dark_pos")

app.destroy()
