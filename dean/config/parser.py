from enum import Enum
from typing import Any, Callable, Mapping, Sequence, Type, TypeVar, Union, \
                   cast, get_type_hints


T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')


def parse(tpe: Type[T], value: Any) -> T:
    if tpe == Any:
        return value
    elif type(tpe) == type(Union):
        for union_arg in cast(Union, tpe).__args__:
            try:
                return parse(union_arg, value)
            except TypeError:
                continue

        raise TypeError(
            'Value `{}` does not match type `{}`'.format(value, tpe))
    elif issubclass(tpe, Mapping):
        if not isinstance(value, Mapping):
            raise TypeError(
                'Value `{}` does not match type `{}`'.format(value, tpe))

        key_t, val_t = getattr(tpe, '__args__', (None, None))
        if key_t:
            return cast(T, parse_mapping(key_t, val_t, value))
        else:
            return cast(T, parse_mapping(Any, Any, value))
    elif issubclass(tpe, Sequence) \
            and not issubclass(tpe, bytes) \
            and not issubclass(tpe, str):
        if not isinstance(value, Sequence):
            raise TypeError(
                'Value `{}` does not match type `{}`'.format(value, tpe))

        item_t = getattr(tpe, '__args__', (None,))[0]
        if item_t:
            return parse_sequence(tpe, item_t, value)
        else:
            return parse_sequence(tpe, Any, value)
    elif issubclass(tpe, Enum):
        try:
            return tpe(value)
        except ValueError:
            try:
                return tpe[value]
            except KeyError:
                raise TypeError(
                    'No matching value for `{}` of enum for type `{}`'.format(
                        value, tpe))
    elif get_type_hints(tpe):
        return parse_hinted(tpe, value)
    elif not isinstance(value, tpe):
        raise TypeError(
            'Value `{}` does not match type `{}`'.format(value, tpe))
    else:
        return cast(tpe, value)


def parse_sequence(seq_type: Type[Sequence], item_type: Type[T],
                   seq: Sequence[Any]) -> Sequence[T]:
    sequence_type: Callable = type(seq)

    def gen_items():
        for item in seq:
            parsed = parse(item_type, item)
            yield parsed

    return sequence_type(gen_items())


def parse_mapping(key_type: Type[K], value_type: Type[V],
                  dict_: Mapping[Any, Any]) -> Mapping[K, V]:
    dict_type = type(dict_)

    def gen_items():
        for key, value in dict_.items():
            key = parse(key_type, key)
            value = parse(value_type, value)
            yield cast(key_type, key), cast(value_type, value)

    return dict_type(gen_items())


def parse_hinted(tpe: Type[T], value: Any) -> T:
    if isinstance(value, tpe):
        return value
    elif not isinstance(value, Mapping):
        raise TypeError(
           'Value `{}` must be a Mapping to build a `{}`'.format(value, tpe))

    hints = get_type_hints(tpe)

    def gen_fields():
        for field_name, field_type in hints.items():
            # Ignore missing fields to allow default values. Constructing the
            # object will fail later if a mandatory field is not present.
            if field_name not in value:
                continue

            yield field_name, parse(field_type, value[field_name])

    fields = dict(gen_fields())
    return tpe(**fields)
