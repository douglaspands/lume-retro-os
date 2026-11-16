"""Minimal flattened device tree (DTB) reader and writer.

Enough to read the `lume-select` node of the built DTBs (boot-dtb-select D3) and to write
the small device trees the tests of lume-bootsel use as candidates and as the running
tree. Not a general tool: no memory reservations on write, no phandle handling.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = 0xD00DFEED
_BEGIN_NODE, _END_NODE, _PROP, _NOP, _END = 1, 2, 3, 4, 9


@dataclass
class Node:
    props: dict[str, bytes] = field(default_factory=dict)
    children: dict[str, "Node"] = field(default_factory=dict)

    def path(self, path: str) -> "Node | None":
        node: Node | None = self
        for part in [p for p in path.split("/") if p]:
            node = node.children.get(part) if node else None
        return node

    def string(self, name: str) -> str | None:
        value = self.props.get(name)
        return None if value is None else value.split(b"\0", 1)[0].decode()

    def strings(self, name: str) -> list[str]:
        value = self.props.get(name, b"")
        return [s.decode() for s in value.split(b"\0") if s]

    def cells(self, name: str) -> list[int]:
        value = self.props.get(name, b"")
        return list(struct.unpack(f">{len(value) // 4}I", value))


def parse(data: bytes) -> Node:
    magic, _total, off_struct, off_strings, *_ = struct.unpack_from(">10I", data, 0)
    if magic != MAGIC:
        raise ValueError("not a device tree (bad magic)")

    def name_at(off: int) -> str:
        end = data.index(b"\0", off_strings + off)
        return data[off_strings + off:end].decode()

    pos = off_struct
    stack: list[Node] = []
    root: Node | None = None
    while True:
        (token,) = struct.unpack_from(">I", data, pos)
        pos += 4
        if token == _BEGIN_NODE:
            end = data.index(b"\0", pos)
            name = data[pos:end].decode()
            pos = (end + 4) & ~3
            node = Node()
            if stack:
                stack[-1].children[name] = node
            else:
                root = node
            stack.append(node)
        elif token == _END_NODE:
            stack.pop()
        elif token == _PROP:
            length, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            stack[-1].props[name_at(nameoff)] = data[pos:pos + length]
            pos = (pos + length + 3) & ~3
        elif token == _NOP:
            continue
        elif token == _END:
            break
        else:
            raise ValueError(f"bad token {token:#x} at {pos - 4}")
    assert root is not None
    return root


def build(root: Node) -> bytes:
    strings = bytearray()
    offsets: dict[str, int] = {}
    body = bytearray()

    def string_off(name: str) -> int:
        if name not in offsets:
            offsets[name] = len(strings)
            strings.extend(name.encode() + b"\0")
        return offsets[name]

    def pad() -> None:
        body.extend(b"\0" * (-len(body) % 4))

    def emit(name: str, node: Node) -> None:
        body.extend(struct.pack(">I", _BEGIN_NODE) + name.encode() + b"\0")
        pad()
        for pname, value in node.props.items():
            body.extend(struct.pack(">III", _PROP, len(value), string_off(pname)) + value)
            pad()
        for cname, child in node.children.items():
            emit(cname, child)
        body.extend(struct.pack(">I", _END_NODE))

    emit("", root)
    body.extend(struct.pack(">I", _END))
    off_rsvmap = 40
    off_struct = off_rsvmap + 16          # one empty reservation entry
    off_strings = off_struct + len(body)
    total = off_strings + len(strings)
    header = struct.pack(">10I", MAGIC, total, off_struct, off_strings, off_rsvmap,
                         17, 16, 0, len(strings), len(body))
    return header + bytes(16) + bytes(body) + bytes(strings)


# --- helpers for property values -------------------------------------------------------

def s(*values: str) -> bytes:
    """A string or string-list property."""
    return b"".join(v.encode() + b"\0" for v in values)


def u32(*values: int) -> bytes:
    return struct.pack(f">{len(values)}I", *values)


def select_info(root: Node) -> dict | None:
    """The `lume-select` node of a DTB (D3): id, priority, default, rules; None without it."""
    node = root.children.get("lume-select")
    if node is None:
        return None
    return {"id": node.string("lume,id"),
            "priority": (node.cells("lume,priority") or [0])[0],
            "default": "lume,default" in node.props,
            "rules": {k: node.cells(k) for k in ("lume,adc", "lume,gpio", "lume,i2c-present")
                      if k in node.props}}
