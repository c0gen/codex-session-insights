"""Bounded protobuf wire parsing without text guessing or partial acceptance."""


class WireError(ValueError):
    pass


def varint(data, position):
    value = 0
    for shift in range(0, 70, 7):
        if position >= len(data):
            raise WireError("truncated_varint")
        byte = data[position]
        position += 1
        if shift == 63 and byte > 1:
            raise WireError("overflow_varint")
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, position
    raise WireError("overflow_varint")


def fields(data, max_fields=200000):
    position, count = 0, 0
    while position < len(data):
        count += 1
        if count > max_fields:
            raise WireError("field_limit")
        tag, position = varint(data, position)
        number, kind = tag >> 3, tag & 7
        if not 0 < number < 2**29 or kind not in (0, 1, 2, 5):
            raise WireError("invalid_field")
        if kind == 0:
            value, position = varint(data, position)
        else:
            if kind == 2:
                size, position = varint(data, position)
            else:
                size = 8 if kind == 1 else 4
            if size > len(data) - position:
                raise WireError("truncated_field")
            value = data[position:position + size]
            position += size
        yield number, kind, value


def message(data):
    result = {}
    for number, kind, value in fields(data):
        result.setdefault(number, []).append(value)
    return result
