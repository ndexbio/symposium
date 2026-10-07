"""The rules the gate applies, shared by the skill's tools and the data server's Data API.

Standard library only, Python 3.9+, so the skill runs it with any host Python and the data
server image ships the same package. `validate` is the specification's validator; `checks`
holds the gate's skip rule and the publish-time naming and payload limits.
"""
