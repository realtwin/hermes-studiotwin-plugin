"""Bounded JSON metadata reader, including JSON inside MCP text blocks.

Input strings are drained, not buffered, beyond 16 KiB. Binary downloads do
not use this reader. URLs (including signed and s3 URLs) remain untouched.
"""
import codecs
import itertools
import json

INPUT_STRING_LIMIT = 16 * 1024
INPUT_BUDGET = 64 * 1024
NOTE = '[inputs too large to display]'


class MetadataLimit(ValueError):
    """Safety limits are not recoverable non-JSON ancillary tool text."""


class MetadataJSON:
    def __init__(self, chars, budget=None, unwrap_text=True):
        self.chars = iter(chars)
        self.current = next(self.chars, '')
        self.budget = budget if budget is not None else [8 * 1024 * 1024]
        self.unwrap_text = unwrap_text

    def advance(self):
        c = self.current
        self.current = next(self.chars, '')
        return c

    def space(self):
        while self.current and self.current.isspace():
            self.advance()

    def charge(self, n):
        self.budget[0] -= n
        if self.budget[0] < 0:
            raise MetadataLimit('metadata budget exceeded')

    def decoded_string(self):
        if self.advance() != '"':
            raise ValueError('expected string')
        while self.current != '"':
            c = self.advance()
            if not c or ord(c) < 32:
                raise ValueError('invalid string')
            if c == '\\':
                escape = self.advance()
                if escape == 'u':
                    digits = ''.join(self.advance() for _ in range(4))
                    if len(digits) != 4:
                        raise ValueError('invalid escape')
                    c = chr(int(digits, 16))
                else:
                    escapes = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
                    if escape not in escapes:
                        raise ValueError('invalid escape')
                    c = escapes[escape]
            yield c
        self.advance()

    def string(self, inputs=None, embedded=False):
        chars = self.decoded_string()
        if embedded:
            # Tool text is itself JSON. Parse its decoded characters directly,
            # never materializing the original multi-megabyte text block.
            prefix = []
            for c in chars:
                prefix.append(c)
                if not c.isspace():
                    break
                if len(prefix) > 1024:
                    break
            if prefix and prefix[-1] in '{[':
                captured = []
                total = 0
                def capture():
                    nonlocal total
                    for char in itertools.chain(prefix, chars):
                        total += 1
                        if len(captured) < INPUT_STRING_LIMIT:
                            captured.append(char)
                        yield char
                stream = capture()
                nested = MetadataJSON(stream, self.budget, unwrap_text=False)
                try:
                    value = nested.document()
                    return json.dumps(value, ensure_ascii=True)
                except MetadataLimit:
                    raise
                except ValueError:
                    # MCP may include prose alongside structuredContent. A
                    # JSON-looking first character is not a JSON contract.
                    for _ in stream:
                        pass
                    text = ''.join(captured)
                    self.charge(len(text.encode('utf-8', errors='surrogatepass')))
                    return text if total <= INPUT_STRING_LIMIT else '[tool text too large to display]'
            chars = itertools.chain(prefix, chars)
        # Signed HTTPS and s3 references are not inline media; never redact them.
        prefix = list(itertools.islice(chars, 8))
        reference = ''.join(prefix).lower().startswith(('https://', 'http://', 's3://'))
        chars = itertools.chain(prefix, chars)
        parts, size, dropped = [], 0, False
        for c in chars:
            size += len(c.encode('utf-8', errors='surrogatepass'))
            if inputs is not None and not reference and (size > INPUT_STRING_LIMIT or inputs[0] <= 0):
                dropped = True
                continue
            if inputs is not None:
                inputs[0] -= len(c.encode('utf-8', errors='surrogatepass'))
            self.charge(len(c.encode('utf-8', errors='surrogatepass')))
            parts.append(c)
        if dropped:
            assert inputs is not None
            retained = sum(len(c.encode('utf-8', errors='surrogatepass')) for c in parts)
            inputs[0] += retained
            self.budget[0] += retained
            inputs[1] = True
            return NOTE
        # Match stdlib JSON's combining of escaped UTF-16 surrogate pairs.
        return json.loads(json.dumps(''.join(parts)))

    def value(self, inputs=None, depth=0, embedded=False, path=()):
        if depth > 64:
            raise MetadataLimit('metadata nesting exceeded')
        self.space()
        self.charge(16)  # bound node/container overhead as well as strings
        if self.current == '"':
            return self.string(inputs, embedded)
        if self.current == '{':
            self.advance()
            result = {}
            self.space()
            while self.current != '}':
                key = self.string()
                self.space()
                if self.advance() != ':':
                    raise ValueError('expected colon')
                own_inputs = [INPUT_BUDGET, False] if key == 'inputs' else inputs
                result[key] = self.value(own_inputs, depth + 1, path=path + (key,),
                    embedded=(self.unwrap_text and path == ('result', 'content', '*') and key == 'text'))
                if key == 'inputs' and own_inputs is not None and own_inputs[1]:
                    result['inputs_truncated'] = True
                self.space()
                if self.current == '}':
                    break
                if self.advance() != ',':
                    raise ValueError('expected comma')
                self.space()
                if self.current == '}':
                    raise ValueError('trailing comma')
            self.advance()
            return result
        if self.current == '[':
            self.advance()
            result = []
            self.space()
            while self.current != ']':
                result.append(self.value(inputs, depth + 1, path=path + ('*',)))
                self.space()
                if self.current == ']':
                    break
                if self.advance() != ',':
                    raise ValueError('expected comma')
                self.space()
                if self.current == ']':
                    raise ValueError('trailing comma')
            self.advance()
            return result
        token = []
        while self.current and self.current not in ',]} \r\n\t':
            token.append(self.advance())
            if len(token) > 128:
                raise ValueError('invalid scalar')
        return json.loads(''.join(token))

    def document(self):
        value = self.value()
        self.space()
        if self.current:
            raise ValueError('trailing metadata')
        return value


def read_metadata(chunks, content_type, sequence, wire_limit=128 * 1024 * 1024):
    def characters():
        decoder = codecs.getincrementaldecoder('utf-8')()
        size = 0
        for chunk in chunks:
            size += len(chunk)
            if size > wire_limit:
                raise MetadataLimit('metadata wire budget exceeded')
            yield from decoder.decode(chunk)
        yield from decoder.decode(b'', final=True)
    chars = characters()
    if not content_type.startswith('text/event-stream'):
        return MetadataJSON(chars).document()
    # Event data is a lazy character iterator; even multiline SSE events never
    # allocate a full line/frame. Ignore comments and non-data SSE fields.
    chars = iter(chars)
    exhausted = False
    budget = [8 * 1024 * 1024]
    def event():
        nonlocal exhausted
        first_data = True
        while True:
            c = next(chars, '')
            if not c:
                exhausted = True
                return
            if c == '\r':
                c = next(chars, '')
            if c == '\n':
                return
            field = []
            while c and c not in ':\r\n':
                field.append(c)
                if len(field) > 1024:
                    raise MetadataLimit('excessive SSE field')
                c = next(chars, '')
            is_data = ''.join(field) == 'data'
            if c == ':':
                c = next(chars, '')
                if c == ' ':
                    c = next(chars, '')
            if is_data:
                if not first_data:
                    yield '\n'
                first_data = False
            while c and c != '\n':
                if is_data and c != '\r':
                    yield c
                c = next(chars, '')
            if not c:
                exhausted = True
                return
    while not exhausted:
        reader = MetadataJSON(event(), budget)
        if not reader.current:
            continue
        value = reader.document()
        if isinstance(value, dict) and value.get('id') == sequence:
            return value
    raise ValueError('no matching MCP event')
