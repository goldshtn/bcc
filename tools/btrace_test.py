#!/usr/bin/env python

from btrace import *
import unittest

class TokenizerTests(unittest.TestCase):
        def assertToken(self, expected, token):
                self.assertEqual(expected[0], token[0])
                self.assertEqual(expected[1], token[1])

        def test_empty(self):
                t = Tokenizer("")
                self.assertEqual(TokenType.EOF, t.next_token()[0])

        def test_whitespace(self):
                t = Tokenizer("  \t \n")
                self.assertEqual(TokenType.EOF, t.next_token()[0])

        def test_identifier(self):
                t = Tokenizer("  ident123 ")
                self.assertToken((TokenType.IDENTIFIER, "ident123"), t.next_token())
                self.assertEqual(TokenType.EOF, t.next_token()[0])

        def test_special_char(self):
                t = Tokenizer("p:c")
                t.next_token()
                self.assertToken((TokenType.PROBE_SPEC_SEPARATOR, ":"), t.next_token())

        def test_raw_token_until(self):
                t = Tokenizer("func123_abc(int a, void *b) ")
                self.assertToken((TokenType.IDENTIFIER, "func123_abc"), t.next_token())
                self.assertToken((TokenType.OPEN_PAREN, "("), t.next_token())
                self.assertToken((TokenType.RAW, "int a, void *b"), t.raw_token_until(")"))

        def test_raw_token_until_newline(self):
                t = Tokenizer("abcdef\n123[123")
                self.assertToken((TokenType.RAW, "abcdef\n123"), t.raw_token_until("["))

        def test_raw_token_until_balanced(self):
                t = Tokenizer(" { whatever(); if (something) { whatever(); } } ")
                self.assertToken((TokenType.OPEN_BRACE, "{"), t.next_token())
                self.assertToken((TokenType.RAW, " whatever(); if (something) { whatever(); } "),
                                 t.raw_token_until_balanced("}"))

        def test_raw_token_until_balanced2(self):
                t = Tokenizer("abc(int (*)(int (*pfn))), foo()); int foo(int (*));")
                self.assertToken((TokenType.RAW, "abc(int (*)(int (*pfn))), foo()"),
                                 t.raw_token_until_balanced(")"))

        def test_raw_token_until_balanced3(self):
                t = Tokenizer(" whatever();")
                self.assertToken((TokenType.RAW, " whatever();"),
                                 t.raw_token_until_balanced("}"))

        def test_line_and_col(self):
                t = Tokenizer("whatever\n  :")
                self.assertToken((TokenType.IDENTIFIER, "whatever"), t.next_token())
                self.assertToken((TokenType.PROBE_SPEC_SEPARATOR, ":"), t.next_token())
                self.assertEqual(2, t.line)
                self.assertEqual(4, t.col)

        def test_raw_token_until_position(self):
                t = Tokenizer("a]bc")
                t.raw_token_until("]")
                self.assertEqual(2, t.position)       # ] was consumed

class ParserTests(unittest.TestCase):
        def test_parse_probe_decl(self):
                p = ProgramParser("p::__kmalloc(size_t size)")
                decl = p._parse_probe_decl()
                self.assertEqual("p", decl.probe_type)
                self.assertEqual("kernel", decl.library)
                self.assertEqual("__kmalloc", decl.function)
                self.assertEqual("size_t size", decl.signature)

        def test_parse_probe_decl2(self):
                p = ProgramParser("r::kfree {}")
                decl = p._parse_probe_decl()
                self.assertEqual("r", decl.probe_type)
                self.assertEqual("kernel", decl.library)
                self.assertEqual("kfree", decl.function)
                self.assertEqual("", decl.signature)

        def test_parse_probe_decl3(self):
                p = ProgramParser("::BEGIN {}")
                decl = p._parse_probe_decl()
                self.assertEqual("b", decl.probe_type)
                self.assertEqual("", decl.library)
                self.assertEqual("BEGIN", decl.function)
                self.assertEqual("", decl.signature)

        def test_parse_probe_decl4(self):
                p = ProgramParser("p:c:write(int fd, void *buf, size_t size) /1/")
                decl = p._parse_probe_decl()
                self.assertEqual("p", decl.probe_type)
                self.assertEqual("c", decl.library)
                self.assertEqual("write", decl.function)
                self.assertEqual("int fd, void *buf, size_t size", decl.signature)

        def test_parse_predicate(self):
                p = ProgramParser("/arg0 && size > 17/")
                pred = p._parse_predicate()
                self.assertEqual("arg0 && size > 17", pred.predicate)

        def test_parse_empty_actions(self):
                p = ProgramParser("{ }")
                actions = p._parse_actions()
                self.assertEqual([""], actions.actions)

        def test_parse_singleline_actions(self):
                p = ProgramParser("{ printf(\"whatever\\n\"); }")
                actions = p._parse_actions()
                self.assertEqual(["printf(\"whatever\\n\");" ], actions.actions)

        def test_parse_multiline_actions(self):
                p = ProgramParser("{abc();\ndef();}")
                actions = p._parse_actions()
                self.assertEqual(["abc();", "def();"], actions.actions)

        def test_parse_decl_and_predicate(self):
                p = ProgramParser("p:c:malloc(size_t size) /size>10/")
                decl = p._parse_probe_decl()
                pred = p._parse_predicate()
                self.assertEqual("malloc", decl.function)
                self.assertEqual("size_t size", decl.signature)
                self.assertEqual("size>10", pred.predicate)

        def test_canonic_parse(self):
                p = ProgramParser("p::__kmalloc(size_t size) /size/ { printf(\"%d\\n\", size); }")
                p._parse_program()      # TODO

if __name__ == "__main__":
        unittest.main()
