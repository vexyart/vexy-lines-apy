# this_file: tests/test_types.py
"""Tests for vexy_lines_api.types module."""

from __future__ import annotations

from vexy_lines_api.types import DocumentInfo, LayerNode, NewDocumentResult, RenderStatus


class TestDocumentInfo:
    """Tests for the DocumentInfo dataclass."""

    def test_construction(self):
        info = DocumentInfo(width_mm=210.0, height_mm=297.0, resolution=300.0, units="mm", has_changes=False)
        assert info.width_mm == 210.0
        assert info.height_mm == 297.0
        assert info.resolution == 300.0
        assert info.units == "mm"
        assert info.has_changes is False

    def test_has_changes_true(self):
        info = DocumentInfo(width_mm=100.0, height_mm=100.0, resolution=72.0, units="px", has_changes=True)
        assert info.has_changes is True

    def test_equality(self):
        a = DocumentInfo(width_mm=210.0, height_mm=297.0, resolution=300.0, units="mm", has_changes=False)
        b = DocumentInfo(width_mm=210.0, height_mm=297.0, resolution=300.0, units="mm", has_changes=False)
        assert a == b


class TestLayerNode:
    """Tests for the LayerNode dataclass and from_dict classmethod."""

    def test_construction_minimal(self):
        node = LayerNode(id=1, type="document", caption="Root", visible=True)
        assert node.id == 1
        assert node.type == "document"
        assert node.caption == "Root"
        assert node.visible is True
        assert node.fill_type is None
        assert node.children == []

    def test_construction_with_fill_type(self):
        node = LayerNode(id=5, type="fill", caption="Linear Fill", visible=True, fill_type="linear")
        assert node.fill_type == "linear"

    def test_construction_with_children(self):
        child = LayerNode(id=2, type="layer", caption="Layer 1", visible=True)
        parent = LayerNode(id=1, type="group", caption="Group 1", visible=True, children=[child])
        assert len(parent.children) == 1
        assert parent.children[0].caption == "Layer 1"

    def test_from_dict_minimal(self):
        d = {"id": 1, "type": "document", "caption": "Root", "visible": True}
        node = LayerNode.from_dict(d)
        assert node.id == 1
        assert node.type == "document"
        assert node.caption == "Root"
        assert node.visible is True

    def test_from_dict_defaults(self):
        """Missing caption defaults to empty string, missing visible defaults to True."""
        d = {"id": 1, "type": "document"}
        node = LayerNode.from_dict(d)
        assert node.caption == ""
        assert node.visible is True

    def test_from_dict_with_fill_type(self):
        d = {"id": 5, "type": "fill", "caption": "Wave", "visible": True, "fill_type": "wave"}
        node = LayerNode.from_dict(d)
        assert node.fill_type == "wave"

    def test_from_dict_fill_type_none(self):
        d = {"id": 5, "type": "group", "caption": "G", "visible": True, "fill_type": None}
        node = LayerNode.from_dict(d)
        assert node.fill_type is None

    def test_from_dict_recursive_children(self):
        d = {
            "id": 1,
            "type": "document",
            "caption": "Root",
            "visible": True,
            "children": [
                {
                    "id": 2,
                    "type": "group",
                    "caption": "Group 1",
                    "visible": True,
                    "children": [
                        {"id": 3, "type": "layer", "caption": "Layer 1", "visible": True},
                        {
                            "id": 4,
                            "type": "layer",
                            "caption": "Layer 2",
                            "visible": False,
                            "children": [
                                {"id": 5, "type": "fill", "caption": "Fill", "visible": True, "fill_type": "linear"},
                            ],
                        },
                    ],
                },
            ],
        }
        node = LayerNode.from_dict(d)
        assert node.id == 1
        assert len(node.children) == 1
        group = node.children[0]
        assert group.type == "group"
        assert len(group.children) == 2
        layer2 = group.children[1]
        assert layer2.visible is False
        assert len(layer2.children) == 1
        assert layer2.children[0].fill_type == "linear"

    def test_from_dict_empty_children(self):
        d = {"id": 1, "type": "layer", "children": []}
        node = LayerNode.from_dict(d)
        assert node.children == []

    def test_from_dict_no_children_key(self):
        d = {"id": 1, "type": "layer"}
        node = LayerNode.from_dict(d)
        assert node.children == []

    def test_default_children_not_shared(self):
        """Each instance should get its own default children list."""
        a = LayerNode(id=1, type="layer", caption="A", visible=True)
        b = LayerNode(id=2, type="layer", caption="B", visible=True)
        a.children.append(LayerNode(id=3, type="fill", caption="F", visible=True))
        assert len(b.children) == 0


class TestNewDocumentResult:
    """Tests for the NewDocumentResult dataclass."""

    def test_construction(self):
        result = NewDocumentResult(status="ok", width=1920.0, height=1080.0, dpi=300.0, root_id=42)
        assert result.status == "ok"
        assert result.width == 1920.0
        assert result.height == 1080.0
        assert result.dpi == 300.0
        assert result.root_id == 42

    def test_equality(self):
        a = NewDocumentResult(status="ok", width=100.0, height=100.0, dpi=72.0, root_id=1)
        b = NewDocumentResult(status="ok", width=100.0, height=100.0, dpi=72.0, root_id=1)
        assert a == b


class TestRenderStatus:
    """Tests for the RenderStatus dataclass."""

    def test_rendering_true(self):
        status = RenderStatus(rendering=True)
        assert status.rendering is True

    def test_rendering_false(self):
        status = RenderStatus(rendering=False)
        assert status.rendering is False

    def test_equality(self):
        assert RenderStatus(rendering=True) == RenderStatus(rendering=True)
        assert RenderStatus(rendering=True) != RenderStatus(rendering=False)
