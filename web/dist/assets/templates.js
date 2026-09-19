export const templates = [
    {
        "name": "Event normalization",
        "description": "Validate an event and map its fields.",
        "definition": {
            "schema_version": 1,
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string"
                    },
                    "amount": {
                        "type": "number"
                    }
                },
                "required": [
                    "name",
                    "amount"
                ],
                "additionalProperties": false
            },
            "nodes": [
                {
                    "id": "receive",
                    "type": "set",
                    "label": "Map incoming event",
                    "values": {
                        "name": {
                            "$ref": "input.name"
                        },
                        "amount": {
                            "$ref": "input.amount"
                        },
                        "source": "webhook"
                    }
                },
                {
                    "id": "check",
                    "type": "condition",
                    "label": "Validate amount",
                    "depends_on": [
                        "receive"
                    ],
                    "predicate": {
                        "left": {
                            "$ref": "steps.receive.amount"
                        },
                        "op": "gt",
                        "right": 0
                    }
                },
                {
                    "id": "confirm",
                    "type": "set",
                    "label": "Prepare receipt",
                    "depends_on": [
                        "check"
                    ],
                    "when": {
                        "left": {
                            "$ref": "steps.check.match"
                        },
                        "op": "eq",
                        "right": true
                    },
                    "values": {
                        "accepted": true,
                        "name": {
                            "$ref": "steps.receive.name"
                        }
                    }
                }
            ]
        }
    },
    {
        "name": "Lead triage",
        "description": "AI classification with an explicit operator review.",
        "definition": {
            "schema_version": 1,
            "input_schema": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "minLength": 1
                    },
                    "message": {
                        "type": "string",
                        "maxLength": 4000
                    },
                    "budget": {
                        "type": "number",
                        "minimum": 0
                    }
                },
                "required": [
                    "company",
                    "message",
                    "budget"
                ],
                "additionalProperties": false
            },
            "nodes": [
                {
                    "id": "normalize",
                    "type": "set",
                    "label": "Normalize request",
                    "values": {
                        "company": {
                            "$ref": "input.company"
                        },
                        "message": {
                            "$ref": "input.message"
                        },
                        "budget": {
                            "$ref": "input.budget"
                        }
                    }
                },
                {
                    "id": "qualify",
                    "type": "condition",
                    "label": "Check project budget",
                    "depends_on": [
                        "normalize"
                    ],
                    "predicate": {
                        "left": {
                            "$ref": "steps.normalize.budget"
                        },
                        "op": "gte",
                        "right": 5000
                    }
                },
                {
                    "id": "classify",
                    "type": "ai",
                    "label": "Classify inquiry",
                    "depends_on": [
                        "qualify"
                    ],
                    "when": {
                        "left": {
                            "$ref": "steps.qualify.match"
                        },
                        "op": "eq",
                        "right": true
                    },
                    "provider": "mock",
                    "model": "fixture",
                    "prompt": {
                        "$ref": "steps.normalize.message"
                    },
                    "mock_response": {
                        "category": "integration",
                        "priority": "normal",
                        "summary": "Review an integration request"
                    },
                    "response_schema": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string"
                            },
                            "priority": {
                                "type": "string"
                            },
                            "summary": {
                                "type": "string"
                            }
                        },
                        "required": [
                            "category",
                            "priority",
                            "summary"
                        ],
                        "additionalProperties": false
                    }
                },
                {
                    "id": "review",
                    "type": "approval",
                    "label": "Operator approval",
                    "depends_on": [
                        "classify"
                    ],
                    "message": "Confirm that this inquiry can be routed to the team.",
                    "expires_after": 86400
                },
                {
                    "id": "route",
                    "type": "set",
                    "label": "Prepare handoff",
                    "depends_on": [
                        "review"
                    ],
                    "values": {
                        "company": {
                            "$ref": "input.company"
                        },
                        "category": {
                            "$ref": "steps.classify.category"
                        },
                        "status": "ready_for_handoff"
                    }
                }
            ]
        }
    },
    {
        "name": "Reviewed delivery",
        "description": "Approve a request before sending it to an external service.",
        "definition": {
            "schema_version": 1,
            "input_schema": {
                "type": "object"
            },
            "nodes": [
                {
                    "id": "prepare",
                    "type": "set",
                    "label": "Map request",
                    "values": {
                        "event": "inquiry.created"
                    }
                },
                {
                    "id": "review",
                    "type": "approval",
                    "label": "Approve delivery",
                    "depends_on": [
                        "prepare"
                    ],
                    "message": "This step will send data to the configured remote endpoint."
                },
                {
                    "id": "deliver",
                    "type": "http",
                    "label": "Deliver event",
                    "depends_on": [
                        "review"
                    ],
                    "method": "POST",
                    "url": "https://example.com/flowpilot/events",
                    "body": {
                        "$ref": "steps.prepare.event"
                    },
                    "retry": {
                        "max_attempts": 1
                    }
                }
            ]
        }
    }
];
//# sourceMappingURL=templates.js.map