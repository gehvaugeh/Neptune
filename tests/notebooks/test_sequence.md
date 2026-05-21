# Neptune Key Sequence Test

Expect: Neptune Multi-User

Action: !echo "Sequence Test" <return>
Expect: Sequence Test

Action: s
Expect: MODE: SELECTION

Action: j
Expect: Sequence Test

Action: <esc>
Expect: MODE: NORMAL
