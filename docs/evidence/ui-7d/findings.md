# ui-7d — journal toolbar alignment (findings)

## Audit
Measured live: search h=31 fs=12.8px, export h=25 fs=10.88px, lock h=26 fs=11.2px — three heights,
three font sizes, bottoms not aligned.

## Fix
One toolbar rule gives the search input and both buttons height:30px + font-size:0.74rem, centers the
buttons' content, and cancels the `.jrnl-tags` margin-top leaking onto the search input.

## Verify
After: all three are h=30, top=115, fs=11.84px (verify.py asserts equal heights + tops within 1px).
