"""One texture registry for everything. Dear PyGui keeps a registry item
for every `with dpg.texture_registry():` block, so one made per texture -
per geometry change, per build, per thumbnail - was an item that never
went away (the soak counted them). Textures go under this one:

    dpg.add_dynamic_texture(w, h, data, tag=tag, parent=registry())
"""
import dearpygui.dearpygui as dpg

TAG = "tex_registry"


def registry():
    if not dpg.does_item_exist(TAG):
        dpg.add_texture_registry(tag=TAG)
    return TAG
