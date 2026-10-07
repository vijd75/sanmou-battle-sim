#pragma once

#include <map>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

namespace sanmou {

class Json {
public:
    using Array = std::vector<Json>;
    using Object = std::map<std::string, Json>;
    using Value = std::variant<std::nullptr_t, bool, double, std::string, Array, Object>;

    Json();
    explicit Json(Value value);

    static Json parse(const std::string& text);

    bool is_object() const;
    bool contains(const std::string& key) const;
    const Json& at(const std::string& key) const;
    const Array& as_array() const;
    const std::string& as_string() const;
    double as_number() const;
    int as_int() const;

private:
    Value value_;
};

class JsonError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

} // namespace sanmou
