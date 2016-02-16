#!/usr/bin/env python

class TokenType:
        PROBE_SPEC_SEPARATOR = 1        # :
        PREDICATE_SEPARATOR = 2         # /
        IDENTIFIER = 3                  # non-whitespace
        OPEN_BRACE = 4                  # {
        CLOSE_BRACE = 5                 # }
        OPEN_PAREN = 6                  # (
        CLOSE_PAREN = 7                 # )
        RAW = 8                         # raw characters
        EOF = 9

class Tokenizer(object):
        SPECIALS = [':', '/', '{', '}', '(', ')']

        def __init__(self, text):
                self.text = text
                self.position = 0
                self.line = 1
                self.col = 1

        def __str__(self):
                return "%s###%s [pos=%d]" % (self.text[:self.position],
                                             self.text[self.position:],
                                             self.position)

        def remaining_text(self):
                return self.text[self.position:]

        def is_at_end(self):
                return self.position == len(self.text)

        def _next_char(self):
                if self.position == len(self.text):
                        return None
                char = self.text[self.position]
                self.position += 1
                if char == '\n':
                        self.line += 1
                        self.col = 1
                else:
                        self.col += 1
                # print("returning: " + char)
                return char

        def _peek_next_char(self):
                if self.position == len(self.text):
                        return None
                return self.text[self.position]

        def _eat_whitespace(self):
                while True:
                        char = self._peek_next_char()
                        if char is None or not char.isspace():
                                break
                        self._next_char()

        def rewind(self, length):
                self.position = max(0, self.position - length)

        def next_token(self):
                self._eat_whitespace()
                value = ""
                while True:
                        if len(value) > 0:
                                char = self._peek_next_char()
                                if (char is None or \
                                    char in Tokenizer.SPECIALS or \
                                    char.isspace()):
                                        result = (TokenType.IDENTIFIER, value)
                                        value = ""
                                        # print("returning ident: " + str(result))
                                        return result
                        char = self._next_char()
                        if char is None:
                                return (TokenType.EOF, None)
                        if char == ":":
                                return (TokenType.PROBE_SPEC_SEPARATOR, char)
                        if char == "/":
                                return (TokenType.PREDICATE_SEPARATOR, char)
                        if char == "{":
                                return (TokenType.OPEN_BRACE, char)
                        if char == "}":
                                return (TokenType.CLOSE_BRACE, char)
                        if char == "(":
                                return (TokenType.OPEN_PAREN, char)
                        if char == ")":
                                return (TokenType.CLOSE_PAREN, char)
                        value += char

        def raw_token_until(self, expected):
                value = ""
                while True:
                        char = self._next_char()
                        if char is None or char == expected:
                                return (TokenType.RAW, value)
                        value += char

        def raw_token_until_balanced(self, expected):
                if expected == "{" or expected == "}":
                        counterpart = "{"
                        expected = "}"
                if expected == "(" or expected == ")":
                        counterpart = "("
                        expected = ")"
                if counterpart is None:
                        raise ValueError("don't know how to balance %s" %
                                         expected)
                balance = 1
                value = ""
                while True:
                        char = self._next_char()
                        if char is None:
                                return (TokenType.RAW, value)
                        if char == counterpart:
                                balance += 1
                        if char == expected:
                                balance -= 1
                        if balance == 0:
                                return (TokenType.RAW, value)
                        value += char

class Predicate(object):
        def __init__(self, predicate):
                self.predicate = predicate

        def __str__(self):
                return self.predicate

class Actions(object):
        def __init__(self, actions):
                self.actions = actions   # separate lines for easier replacement

        def __str__(self):
                return "\n".join(self.actions)

class ProbeDecl(object):
        def __init__(self, probe_type, library, function, signature):
                self.probe_type = probe_type
                self.library = library
                self.function = function
                self.signature = signature
                self._parse_signature()

        def __str__(self):
                return "%s:%s:%s(%s)" % (self.probe_type, self.library,
                                         self.function, self.signature)

        def _parse_signature(self):
                pass    # TODO

class ProgramParser(object):
        def __init__(self, program):
                self.raw_program = program
                self.tokenizer = Tokenizer(program)

        def get_probes(self):
                pass
                # TODO Call _parse_program and return probe objects

        def _bail(self, error):
                raise ValueError("ERROR @ line %d col %d: %s" %
                                 (self.tokenizer.line, self.tokenizer.col,
                                  error))

        def _expect_and_skip(self, tok_type):
                (tok, val) = self.tokenizer.next_token()
                if tok != tok_type:
                        self._bail("expected %s but got %s" % (tok_type, val))

        def _parse_probe_decl(self):
                # [{p,r}]:[library]:function[(signature)]
                (tok, val) = self.tokenizer.next_token()
                if tok == TokenType.IDENTIFIER:
                        if val not in ["p", "r"]:
                                self._bail("probe type must be p or r")
                        probe_type = val
                        self._expect_and_skip(TokenType.PROBE_SPEC_SEPARATOR)
                elif tok == TokenType.PROBE_SPEC_SEPARATOR:
                        probe_type = "b"    # builtin
                else:
                        self._bail("unexpected token: %s" % val)

                (tok, val) = self.tokenizer.next_token()
                if tok == TokenType.IDENTIFIER:
                        library = val
                        self._expect_and_skip(TokenType.PROBE_SPEC_SEPARATOR)
                elif tok == TokenType.PROBE_SPEC_SEPARATOR:
                        library = "kernel" if probe_type != "b" else ""
                else:
                        self._bail("unexpected token: %s" % val)

                (tok, val) = self.tokenizer.next_token()
                if tok != TokenType.IDENTIFIER:
                        self._bail("unexpected token: %s" % val)
                function = val

                (tok, val) = self.tokenizer.next_token()
                if tok == TokenType.OPEN_PAREN:
                        (tok, val) = \
                                self.tokenizer.raw_token_until_balanced(")")
                        signature = val
                else:
                        if tok not in \
                         [TokenType.OPEN_BRACE, TokenType.PREDICATE_SEPARATOR]:
                                self._bail("expected predicate or action")
                        signature = ""                  # no signature, so
                        self.tokenizer.rewind(1)        # either / or {

                return ProbeDecl(probe_type, library, function, signature)

        def _parse_predicate(self):
                # [/anything/] -- the whole thing is optional
                (tok, val) = self.tokenizer.next_token()
                if tok != TokenType.PREDICATE_SEPARATOR:
                        if tok != TokenType.OPEN_BRACE:
                                self._bail("expected predicate or action")
                        self.tokenizer.rewind(1)
                        return Predicate("1")   # always true

                # TODO allow the / symbol inside parens in the predicate
                (tok, val) = self.tokenizer.raw_token_until("/")
                return Predicate(val)

        def _parse_actions(self):
                # { anything }
                (tok, val) = self.tokenizer.next_token()
                if tok != TokenType.OPEN_BRACE:
                        self._bail("expected actions block, got %s" % val)
                (tok, actions) = self.tokenizer.raw_token_until_balanced("}")
                return Actions(map(str.strip, actions.split('\n')))

        def _parse_program(self):
                # Program parts have the following structure:
                # [{p,r}]:[library]:function[(signature)] [/predicate/] { actions }
                while not self.tokenizer.is_at_end():
                        probe = self._parse_probe_decl()
                        predicate = self._parse_predicate()
                        actions = self._parse_actions()
                        print("probe %s with predicate /%s/ actions = { %s }" %
                              (str(probe), str(predicate), str(actions)))
                # TODO Return probe objects

if __name__ == "__main__":
        print("Work in progress...")
        exit(0)
