### superordinate_list
list visible persistent superordinate relationships for the current context.
visibility follows the same settings as `superordinate_message`:
- **descendants**: children, grandchildren, etc.; always visible because this is the original/core behavior
- **parents / ancestors**: shown only when `Allow Parent / Ancestor Messaging` is enabled in the `a0_superordinates` settings
- **siblings**: shown only when `Allow Sibling Messaging` is enabled in the `a0_superordinates` settings
args: none
output is grouped into sections when applicable:
- `Parent / ancestor superordinates`
- `Sibling superordinates`
- `Descendant superordinates`
Each listed entry includes name, id, profile, status, relationship, and creation time when available.
Use listed visible names/ids with `superordinate_message`.
example:
~~~json
{
  "thoughts": ["I want to see all superordinates visible to this context under current relationship settings."],
  "headline": "Listing visible superordinates",
  "tool_name": "superordinate_list",
  "tool_args": {}
}
~~~
