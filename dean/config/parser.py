import logging
from enum import Enum
from typing import Any, Callable, Collection, Dict, Generator, Mapping, \
                   Optional, Tuple, Type, TypeVar, Union, cast, get_type_hints
from typing import TypingMeta as TypingMeta


T = TypeVar('T')
KT = TypeVar('KT')
VT_co = TypeVar('VT_co', covariant=True)

CollectionBuilder = Callable[[Generator[T, None, None]], Collection[T]]
MappingBuilder = Callable[[Generator[Tuple[KT, VT_co], None, None]],
                          Mapping[KT, VT_co]]

MetaTypeElm = Union[type, TypingMeta]
MetaTypeSeq = Tuple[MetaTypeElm, ...]
MetaType = Union[MetaTypeElm, MetaTypeSeq]

logger = logging.getLogger(__name__)


def _remove_type_params(tpe: MetaType) -> MetaTypeSeq:
    def _clean(t: MetaType):
        return getattr(t, '__origin__', None) or t

    if isinstance(tpe, tuple):
        return tuple(map(_clean, tpe))

    return (_clean(tpe),)


def _get_type_hints(obj: Any) -> Optional[Dict[str, Any]]:
    try:
        return get_type_hints(obj)
    except TypeError:
        return None


def _is_type(obj: Any) -> bool:
    return isinstance(obj, type) \
           or isinstance(obj, TypingMeta) \
           or isinstance(type(obj), TypingMeta)


def _type_check(obj: Any, test: MetaType):
    test_types = _remove_type_params(test)

    try:
        if _is_type(obj):
            obj_type = _remove_type_params(obj)[0]
            if obj_type in test_types:
                return True

            return issubclass(obj_type, test_types)
        else:
            return isinstance(obj, test_types)
    except TypeError:
        return False


def parse(tpe: Type[T], value: Any) -> T:
    if _type_check(tpe, (Any, object)):
        return value
    elif _type_check(tpe, Union):
        errors = []
        for union_arg in tpe.__args__:  # type: ignore
            try:
                return parse(union_arg, value)
            except TypeError as e:
                logger.exception('Failed to match type')
                errors.append(e)
                continue

        raise TypeError(
            'Value `{}` does not match type `{}`'.format(value, tpe))
    elif _type_check(tpe, Mapping):
        if not _type_check(value, Mapping):
            raise TypeError(
                'Value `{}` does not match type `{}`'.format(value, tpe))

        key_t, val_t = getattr(tpe, '__args__', (None, None))
        if key_t:
            return cast(T, parse_mapping(key_t, val_t, value))
        else:
            return cast(T, parse_mapping(object, object, value))
    elif _type_check(tpe, Collection) \
            and not issubclass(tpe, bytes) \
            and not issubclass(tpe, str):
        if not _type_check(value, Collection):
            raise TypeError(
                'Value `{}` does not match type `{}`'.format(value, tpe))

        coll_t = cast(Type[Collection], tpe)
        item_t = getattr(tpe, '__args__', (None,))[0]
        if item_t:
            return cast(T, parse_collection(coll_t, item_t, value))
        else:
            return cast(T, parse_collection(coll_t, object, value))
    elif _type_check(tpe, Enum):
        enum_t = cast(Enum, tpe)
        try:
            enum_val = enum_t(value)
        except ValueError:
            try:
                enum_val = enum_t[value]
            except KeyError:
                raise TypeError(
                    'No matching value for `{}` of enum for type `{}`'.format(
                        value, tpe))

        return cast(T, enum_val)
    elif _get_type_hints(tpe):
        return parse_hinted(tpe, value)
    elif not _type_check(value, tpe):
        raise TypeError(
            'Value `{}` does not match type `{}`'.format(value, tpe))
    else:
        return cast(T, value)


def parse_collection(coll_type: Type[Collection], item_type: Type[T],
                     coll: Collection[Any]) -> Collection[T]:
    collection_type: CollectionBuilder[T] = type(coll)

    def gen_items():
        for item in coll:
            parsed = parse(item_type, item)
            yield parsed

    return collection_type(gen_items())


def parse_mapping(key_type: Type[KT], value_type: Type[VT_co],
                  mapping: Mapping[Any, Any]) -> Mapping[KT, VT_co]:
    mapping_type: MappingBuilder[KT, VT_co] = type(mapping)

    def gen_items():
        for key, value in mapping.items():
            key = parse(key_type, key)
            value = parse(value_type, value)
            yield cast(key_type, key), cast(value_type, value)

    return mapping_type(gen_items())


def parse_hinted(tpe: Type[T], value: Any) -> T:
    if _type_check(value, tpe):
        return value
    elif not _type_check(value, Mapping):
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
    builder: Callable[..., T] = tpe
    return builder(**fields)
