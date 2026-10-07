#include "json.h"

#include <cctype>
#include <sstream>

namespace sanmou {
namespace {

class Parser {
public:
    explicit Parser(const std::string& text) : text_(text) {}

    Json parse() {
        Json value = parse_value();
        skip_ws();
        if (pos_ != text_.size()) {
            fail("unexpected trailing text");
        }
        return value;
    }

private:
    Json parse_value() {
        skip_ws();
        if (pos_ >= text_.size()) {
            fail("unexpected end of input");
        }

        char c = text_[pos_];
        if (c == '{') {
            return Json(parse_object());
        }
        if (c == '[') {
            return Json(parse_array());
        }
        if (c == '"') {
            return Json(parse_string());
        }
        if (c == '-' || std::isdigit(static_cast<unsigned char>(c))) {
            return Json(parse_number());
        }
        if (match("true")) {
            return Json(true);
        }
        if (match("false")) {
            return Json(false);
        }
        if (match("null")) {
            return Json(nullptr);
        }
        fail("invalid value");
    }

    Json::Object parse_object() {
        expect('{');
        Json::Object object;
        skip_ws();
        if (peek('}')) {
            ++pos_;
            return object;
        }

        while (true) {
            skip_ws();
            std::string key = parse_string();
            skip_ws();
            expect(':');
            object.emplace(std::move(key), parse_value());
            skip_ws();
            if (peek('}')) {
                ++pos_;
                return object;
            }
            expect(',');
        }
    }

    Json::Array parse_array() {
        expect('[');
        Json::Array array;
        skip_ws();
        if (peek(']')) {
            ++pos_;
            return array;
        }

        while (true) {
            array.push_back(parse_value());
            skip_ws();
            if (peek(']')) {
                ++pos_;
                return array;
            }
            expect(',');
        }
    }

    std::string parse_string() {
        expect('"');
        std::string out;
        while (pos_ < text_.size()) {
            char c = text_[pos_++];
            if (c == '"') {
                return out;
            }
            if (c != '\\') {
                out.push_back(c);
                continue;
            }
            if (pos_ >= text_.size()) {
                fail("bad string escape");
            }
            char escaped = text_[pos_++];
            switch (escaped) {
            case '"':
            case '\\':
            case '/':
                out.push_back(escaped);
                break;
            case 'b':
                out.push_back('\b');
                break;
            case 'f':
                out.push_back('\f');
                break;
            case 'n':
                out.push_back('\n');
                break;
            case 'r':
                out.push_back('\r');
                break;
            case 't':
                out.push_back('\t');
                break;
            default:
                fail("unsupported string escape");
            }
        }
        fail("unterminated string");
    }

    double parse_number() {
        size_t start = pos_;
        if (peek('-')) {
            ++pos_;
        }
        while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_]))) {
            ++pos_;
        }
        if (peek('.')) {
            ++pos_;
            while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_]))) {
                ++pos_;
            }
        }
        return std::stod(text_.substr(start, pos_ - start));
    }

    bool match(const std::string& token) {
        if (text_.compare(pos_, token.size(), token) == 0) {
            pos_ += token.size();
            return true;
        }
        return false;
    }

    bool peek(char c) const {
        return pos_ < text_.size() && text_[pos_] == c;
    }

    void expect(char c) {
        skip_ws();
        if (!peek(c)) {
            std::ostringstream message;
            message << "expected '" << c << "'";
            fail(message.str());
        }
        ++pos_;
    }

    void skip_ws() {
        while (pos_ < text_.size() && std::isspace(static_cast<unsigned char>(text_[pos_]))) {
            ++pos_;
        }
    }

    [[noreturn]] void fail(const std::string& message) const {
        std::ostringstream full;
        full << "JSON parse error at byte " << pos_ << ": " << message;
        throw JsonError(full.str());
    }

    const std::string& text_;
    size_t pos_ = 0;
};

} // namespace

Json::Json() : value_(nullptr) {}

Json::Json(Value value) : value_(std::move(value)) {}

Json Json::parse(const std::string& text) {
    return Parser(text).parse();
}

bool Json::is_object() const {
    return std::holds_alternative<Object>(value_);
}

bool Json::contains(const std::string& key) const {
    if (!is_object()) {
        return false;
    }
    const auto& object = std::get<Object>(value_);
    return object.find(key) != object.end();
}

const Json& Json::at(const std::string& key) const {
    const auto& object = std::get<Object>(value_);
    auto found = object.find(key);
    if (found == object.end()) {
        throw JsonError("missing JSON key: " + key);
    }
    return found->second;
}

const Json::Array& Json::as_array() const {
    return std::get<Array>(value_);
}

const std::string& Json::as_string() const {
    return std::get<std::string>(value_);
}

double Json::as_number() const {
    return std::get<double>(value_);
}

int Json::as_int() const {
    return static_cast<int>(std::get<double>(value_));
}

} // namespace sanmou
