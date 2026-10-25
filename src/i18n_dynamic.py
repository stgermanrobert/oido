"""Strings translated through variables, for tools/i18n_check.py."""


def dynamic_keys():
    import oido
    import oido_engine as E
    keys = []
    for name, _lo, _hi, desc in E.BANDS:
        keys += [name, desc]
    for _k, label, _f, tip in oido.LISTEN_MODES:
        keys += [label, tip]
    for title, html in oido.LEARN_SECTIONS:
        keys += [title, html]
    return keys
