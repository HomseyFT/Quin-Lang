"""Lexical structure: literals, comments, keywords, and their limits."""

import unittest

from compiler.lexer import Lexer, LexError
from compiler.tokens import TokenType
from tests.harness import QuinTestCase


def kinds(source: str):
    return [t.type for t in Lexer(source).tokenize()]


def literals(source: str):
    return [t.literal for t in Lexer(source).tokenize() if t.literal is not None]


class TestNumbers(QuinTestCase):
    def test_decimal(self):
        self.assertEqual(literals("0 7 42 65535"), [0, 7, 42, 65535])

    def test_zero_lexes(self):
        # 0 has a falsy literal, so it is easy to drop when filtering.
        toks = [t for t in Lexer("0").tokenize() if t.type is TokenType.NUMBER]
        self.assertEqual(len(toks), 1)
        self.assertEqual(toks[0].literal, 0)

    def test_hex_both_cases(self):
        self.assertEqual(literals("0xFF 0Xff 0xdead"), [255, 255, 0xDEAD])

    def test_literal_must_fit_16_bits(self):
        with self.assertRaises(LexError) as cm:
            Lexer("65536").tokenize()
        self.assertIn("16 bits", str(cm.exception))

    def test_hex_needs_digits(self):
        with self.assertRaises(LexError) as cm:
            Lexer("0x").tokenize()
        self.assertIn("no digits", str(cm.exception))

    def test_boundary_values_lex(self):
        self.assertEqual(literals("65535 0xFFFF"), [65535, 65535])


class TestStrings(QuinTestCase):
    def test_basic(self):
        self.assertEqual(literals('"hello"'), ["hello"])

    def test_escape_sequences(self):
        self.assertEqual(literals(r'"a\nb"'), ["a\nb"])
        self.assertEqual(literals(r'"a\tb"'), ["a\tb"])
        self.assertEqual(literals(r'"a\rb"'), ["a\rb"])
        self.assertEqual(literals(r'"a\0b"'), ["a\0b"])

    def test_escaped_backslash_is_one_character(self):
        self.assertEqual(literals(r'"a\\b"'), ["a\\b"])

    def test_escaped_quote_does_not_end_the_literal(self):
        self.assertEqual(literals(r'"say \"hi\" now"'), ['say "hi" now'])

    def test_unknown_escape_is_an_error(self):
        # Keeping the backslash would silently produce two characters instead
        # of reporting the typo.
        with self.assertRaises(LexError) as cm:
            Lexer(r'"a\qb"').tokenize()
        self.assertIn("Unknown escape sequence", str(cm.exception))

    def test_a_literal_ending_in_a_backslash_is_unterminated(self):
        with self.assertRaises(LexError) as cm:
            Lexer(r'"oops\"').tokenize()
        self.assertIn("Unterminated string", str(cm.exception))

    def test_may_span_lines(self):
        self.assertEqual(literals('"a\nb"'), ["a\nb"])

    def test_unterminated(self):
        with self.assertRaises(LexError) as cm:
            Lexer('"oops').tokenize()
        self.assertIn("Unterminated string", str(cm.exception))

    def test_empty_string(self):
        self.assertEqual(literals('""'), [""])


class TestCommentsAndWhitespace(QuinTestCase):
    def test_line_comment_is_skipped(self):
        self.assertEqual(kinds("// all of this\n"), [TokenType.EOF])

    def test_comment_after_code(self):
        self.assertEqual(
            kinds("42 // trailing"),
            [TokenType.NUMBER, TokenType.EOF],
        )

    def test_no_block_comments(self):
        # /* is a slash followed by a star, not a comment opener.
        self.assertEqual(
            kinds("/*"), [TokenType.SLASH, TokenType.STAR, TokenType.EOF]
        )

    def test_comment_does_not_swallow_next_line(self):
        self.assertExprPrints("1 // note\n    + 2", "3")


class TestOperatorsAndKeywords(QuinTestCase):
    def test_two_char_operators(self):
        self.assertEqual(
            kinds("== != <= >= && ||"),
            [
                TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL,
                TokenType.LESS_EQUAL, TokenType.GREATER_EQUAL,
                TokenType.AND_AND, TokenType.OR_OR, TokenType.EOF,
            ],
        )

    def test_amp_is_address_of_but_amp_amp_is_and(self):
        self.assertEqual(kinds("&"), [TokenType.AMP, TokenType.EOF])
        self.assertEqual(kinds("@"), [TokenType.AT, TokenType.EOF])
        self.assertEqual(kinds("@x"), [TokenType.AT, TokenType.IDENTIFIER, TokenType.EOF])
        self.assertEqual(kinds("&&"), [TokenType.AND_AND, TokenType.EOF])

    def test_keywords_are_not_identifiers(self):
        self.assertEqual(
            kinds("fn let ptr heapptr vm_asm include"),
            [
                TokenType.FN, TokenType.LET, TokenType.PTR, TokenType.HEAPPTR,
                TokenType.VM_ASM, TokenType.INCLUDE, TokenType.EOF,
            ],
        )

    def test_identifier_with_keyword_prefix(self):
        self.assertEqual(kinds("integer"), [TokenType.IDENTIFIER, TokenType.EOF])

    def test_underscores_allowed(self):
        self.assertEqual(kinds("_a b_1"), [TokenType.IDENTIFIER, TokenType.IDENTIFIER, TokenType.EOF])

    def test_asm_keyword_was_removed(self):
        # The 8086 backend is gone; `asm` is an ordinary identifier again.
        self.assertEqual(kinds("asm"), [TokenType.IDENTIFIER, TokenType.EOF])

    def test_unexpected_character(self):
        with self.assertRaises(LexError) as cm:
            Lexer("$").tokenize()
        self.assertIn("Unexpected character", str(cm.exception))


class TestSourceLocations(QuinTestCase):
    def test_line_numbers_advance(self):
        toks = [t for t in Lexer("1\n2\n3").tokenize() if t.type is TokenType.NUMBER]
        self.assertEqual([t.line for t in toks], [1, 2, 3])

    def test_error_carries_location(self):
        with self.assertRaises(LexError) as cm:
            Lexer("fn main() {\n  $\n}").tokenize()
        self.assertEqual(cm.exception.line, 2)


if __name__ == "__main__":
    unittest.main()
