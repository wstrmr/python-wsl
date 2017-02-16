import re

from ..exceptions import ParseError, LexError
from ..schema import Schema
from ..lexwsl import make_make_wslreader
from .datatypes import Value, Struct, Option, Set, List, Dict


INDENTSPACES = 4


def _chardesc(text, i):
    if i >= len(text):
        return '(EOL)'

    c = text[i]

    if ord(c) < 32:
        return '(0x%.2x)' %(ord(c),)
    else:
        return '"%s"' %(c,)


def parse_space(text, i):
    start = i
    end = len(text)
    if i >= end or text[i] != ' ':
        raise LexError('space character', text, i, i, 'Expected space character (0x20) but found %s' %(_chardesc(text, i),))
    return i + 1


def parse_newline(text, i):
    start = i
    end = len(text)
    if i >= end or text[i] != '\n':
        raise LexError('newline character', text, i, i, 'Expected newline character (0x0a) but found %s' %(_chardesc(text, i),))
    return i + 1


def parse_colon(text, i):
    start = i
    end = len(text)
    if i >= end or text[i] != ':':
        raise LexError('colon character', text, i, i, 'Expected colon (":") character but found %s' %(_chardesc(text, i),))
    return i + 1


def parse_nothing(text, i):
    return i


def number_of_spaces(text, i):
    start = i
    end = len(text)
    if i >= end:
        return -1  # XXX
    while i < end and text[i] == ' ':
        i += 1
    return i - start


def parse_keyword(text, i):
    start = i
    end = len(text)
    while i < end and text[i].isalpha():
        i += 1
    if i == start:
        raise LexError('Keyword', text, i, i, 'Found invalid character %s with no valid consumed characters' %(_chardesc(text, i),))
    return i, text[start:i]


def followed_by_newline(valuereader):
    def parser(text, i):
        i, v = valuereader(text, i)
        i = parse_newline(text, i)
        return i, v
    return parser


def space_and_then(valuereader):
    def space_and_then_reader(text, i):
        i = parse_space(text, i)
        i, v = valuereader(text, i)
        i = parse_newline(text, i)
        return i, v
    return space_and_then_reader


def newline_and_then(valuereader):
    def newline_and_then_reader(text, i):
        i = parse_newline(text, i)
        i, v = valuereader(text, i)
        return i, v
    return newline_and_then_reader


def make_struct_reader(dct, indent):
    def struct_reader(text, i):
        start = i
        end = len(text)

        items = []

        while True:
            nsp = number_of_spaces(text, i)
            if nsp < indent:
                break
            if nsp > indent:
                raise ParseError('struct at indent level %d' %(indent,), text, start, i, 'unexpected indent of %d' %(nsp,))

            i += nsp
            i = parse_colon(text, i)

            i, key = parse_keyword(text, i)
            parsers = dct.get(key)
            if parsers is None:
                raise ParseError('struct', text, start, i, 'Invalid member "%s". Valid members are %s'% (key, list(dct)))
            parse_ws, parse_val, parse_end = parsers

            i = parse_ws(text, i)
            i, val = parse_val(text, i)
            i = parse_end(text, i)

            items.append((key, val))

        struct = {}

        for k, v in items:
            if k not in dct.keys():
                raise ParseError('struct', text, start, i, 'Invalid key: %s' %(k,))
            if k in items:
                raise ParseError('struct', text, start, i, 'Duplicate key: %s' %(k,))
            struct[k] = v
        for k in dct.keys():
            if k not in struct:
                raise ParseError('struct', text, start, i, 'Missing key: %s' %(k,))

        return i, struct
    return struct_reader


def make_option_reader(reader, indent):
    def option_reader(text, i):
        end = len(text)
        if i < end and text[i] == '!':
            i += 1
            i, val = reader(text, i)
        elif i < end and text[i] == '?':
            i, val = i+1, None
            i = parse_newline(text, i)
        else:
            raise ParseError('Expected option ("?", or "!" followed by value)', text, i)
        return i, val
    return option_reader


def make_set_reader(val_reader, end_reader, indent):
    def set_reader(text, i):
        start = i
        end = len(text)

        set_ = set()

        while True:
            nsp = number_of_spaces(text, i)
            if nsp < indent:
                break
            if nsp > indent:
                raise ParseError('set at indent level %d' %(indent,), text, start, i, 'unexpected indent of %d' %(nsp,))

            i += nsp
            i, val = val_reader(text, i)
            i = end_reader(text, i)

            set_.add(val)

        return i, set_

    return set_reader


def make_list_reader(val_reader, end_reader, indent):
    def list_reader(text, i):
        start = i
        end = len(text)

        set_ = set()

        while True:
            nsp = number_of_spaces(text, i)
            if nsp < indent:
                break
            if nsp > indent:
                raise ParseError('list at indent level %d' %(indent,), text, start, i, 'unexpected indent of %d' %(nsp,))

            i += nsp
            i, val = val_reader(text, i)
            i = end_reader(text, i)

            set_.add(val)

        return i, set_

    return list_reader


def make_dict_reader(key_reader, ws_reader, val_reader, end_reader, indent):
    def dict_reader(text, i):
        start = i
        end = len(text)

        dct = {}

        while True:
            nsp = number_of_spaces(text, i)
            if nsp < indent:
                break
            if nsp > indent:
                raise ParseError('dict at indent level %d' %(indent,), text, start, i, 'unexpected indent of %d' %(nsp,))

            i += nsp

            i, key = key_reader(text, i)
            i = ws_reader(text, i)
            i, val = val_reader(text, i)
            i = end_reader(text, i)

            if dct.setdefault(key, val) is not val:
                raise ParseError('dict', text, start, i, 'Duplicate key "%s"' %(key,))

        return i, dct
    return dict_reader


def run_reader(reader, text):
    i, r = reader(text, 0)
    if i != len(text):
        raise ParseError('Unconsumed text', text, i)
    return r


def make_reader_from_spec(make_reader, spec, indent):
    nextindent = indent + INDENTSPACES
    typ = type(spec)

    if typ == Value:
        reader = make_reader(spec.primtype)
        if reader is None:
            raise ValueError('There is no reader for datatype "%s"' %(spec.primtype,))
        return reader

    elif typ == Struct:
        dct = {}
        for k, v in spec.childs.items():
            val_reader = make_reader_from_spec(make_reader, v, nextindent)
            if type(v) == Value:
                ws_reader = parse_space
                end_reader = parse_newline
            elif type(v) == Option:
                ws_reader = parse_space
                end_reader = parse_nothing
            else:
                ws_reader = parse_newline
                end_reader = parse_nothing
            dct[k] = (ws_reader, val_reader, end_reader)
        return make_struct_reader(dct, indent)

    elif typ == Option:
        val_reader = make_reader_from_spec(make_reader, spec.childs['_val_'], indent)
        if type(spec.childs['_val_']) == Value:
            val_reader = space_and_then(val_reader)
        else:
            val_reader = newline_and_then(val_reader)
        return make_option_reader(val_reader, indent)

    elif typ == Set:
        val_reader = make_reader_from_spec(make_reader, spec.childs['_val_'], indent)
        if type(spec.childs['_val_']) == Value:
            end_reader = parse_newline
        else:
            end_reader = parse_nothing
        return make_set_reader(val_reader, end_reader, indent)

    elif typ == List:
        val_reader = make_reader_from_spec(make_reader, spec.childs['_val_'], indent)
        if type(spec.childs['_val_']) == Value:
            end_reader = parse_newline
        else:
            end_reader = parse_nothing
        return make_list_reader(val_reader, end_reader, indent)

    elif typ == Dict:
        key_reader = make_reader_from_spec(make_reader, spec.childs['_key_'], nextindent)
        if type(spec.childs['_val_']) in [Value, Option]:
            ws_reader = parse_space
            end_reader = parse_newline
        else:
            ws_reader = parse_newline
            end_reader = parse_nothing
        val_reader = make_reader_from_spec(make_reader, spec.childs['_val_'], nextindent)
        return make_dict_reader(key_reader, ws_reader, val_reader, end_reader, indent)

    assert False  # missing case


def text2objects(schema, spec, text):
    if not isinstance(schema, Schema):
        raise TypeError()
    if not isinstance(text, str):
        raise TypeError()
    reader = make_reader_from_spec(make_make_wslreader(schema), spec, 0)
    return run_reader(reader, text)
