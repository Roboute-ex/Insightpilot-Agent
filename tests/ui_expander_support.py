"""Test-only bridge for Streamlit 1.63's non-Widget Expander block.

AppTest omits expander bool events from WidgetStates, unlike a real browser.
Only copy the existing bool open state; never click buttons or change requests.
"""
from streamlit.testing.v1.element_tree import ElementTree, Expander


def install_expander_events(monkeypatch):
    original = ElementTree.get_widget_states
    def with_expanders(tree):
        states = original(tree)
        runner = tree._runner
        present = {item.id for item in states.widgets}
        if runner is not None:
            for node in tree:
                if not isinstance(node, Expander) or not node.proto.id or node.proto.id in present:
                    continue
                try:
                    opened = runner.session_state[node.proto.id]
                except KeyError:
                    opened = node.proto.expanded
                if isinstance(opened, bool):
                    item = states.widgets.add()
                    item.id = node.proto.id
                    item.bool_value = opened
        return states
    monkeypatch.setattr(ElementTree, "get_widget_states", with_expanders)
