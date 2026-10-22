"""Compile the small supported JSON-schema subset into explicit llama.cpp GBNF.

Fail closed on unsupported constructs; do not depend on response_format wrappers
silently activating constraints on every server build.
"""
import json

def literal(value):
    return json.dumps(value,ensure_ascii=False)

def json_literal(value):
    return literal(json.dumps(value,ensure_ascii=False,separators=(',',':')))+' ws'

def grammar_for(schema, forbidden_speech=(), *, social_enabled=True):
    rules = {
        # Unbounded whitespace let Gemma spend hundreds of tokens indenting
        # between fields. One optional separator preserves valid JSON and ends.
        'ws': '[ \\t\\n\\r]?',
        'char': r'[^"\\\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})',
        'string': r'"\"" char{0,500} "\"" ws',
        'qchar': r'[^"\\¿?<>*:—\x00-\x1F] | "\\" (["\\/bft] | "u" [0-9a-fA-F]{4})',
        'question': r'"\"¿" qchar{1,498} "?\"" ws',
        'pchar': r'[^"\\¿?<>*:—\x00-\x1F] | "\\" (["\\/bft] | "u" [0-9a-fA-F]{4})',
    }
    # Social interjections are complete utterances, not a gateway for arbitrary
    # third-person narration. Open language remains available for self reactions.
    prefixes = ['Estoy ','Me ','Prefiero ','Quiero ','Puedo ','Tengo ','Necesito ','Creo ','Pienso ','Entiendo ','Escucho ', 'Me parece ','Me pregunto ','Me preocupa ','Me interesa ', 'No estoy ','No quiero ','No puedo ','No tengo ','No necesito ','No entiendo ','No creo ','No sé ','No me ']
    social = ['Hola','Buenas tardes','Buenas noches','Buenos días','Gracias','Sí','No','Claro','Vale','De acuerdo','Bien','Depende','Pues','No sé']
    # Once a character has already used a canned phrase, stop suggesting it
    # at decoding time rather than wasting all retries on the same greeting.
    banned_literal = {v.strip().rstrip('.!?') for v in forbidden_speech}
    social = [p for p in social if p not in banned_literal] if social_enabled else []
    social_expr = ' | '.join([json_literal(p) for p in social] + [json_literal(p+'.') for p in social])
    deny_serial = 0
    def safe_suffix(suffixes, question=False):
        """Finite trie excludes copied prefixes at decoding time, not after commit."""
        nonlocal deny_serial
        char = 'qchar' if question else 'pchar'
        close = literal('?"' if question else '"')+' ws'
        if not suffixes:
            return char+'{0,450} '+close
        if '' in suffixes:
            return None # cannot enter an already-complete copied prefix
        children = sorted({s[0] for s in suffixes})
        # Normal JSON escapes may represent a forbidden character differently;
        # application validation still rejects decoded/normalized echoes.
        escaped = ''.join(c.replace('\\','\\\\').replace(']','\\]').replace('-','\\-').replace('^','\\^') for c in children if c not in '"\\¿?')
        other = '[^"\\\\¿?<>*:—\\x00-\\x1F'+escaped+']'
        alternatives = [close,other+' '+char+'{0,450} '+close]
        for c in children:
            child = safe_suffix([s[1:] for s in suffixes if s[0]==c],question)
            if child:
                alternatives.append(literal(c)+' '+child)
        deny_serial += 1
        name = 'deny'+str(deny_serial)
        rules[name] = ' | '.join(alternatives)
        return name
    banned = [s.strip().rstrip('.!?') for s in forbidden_speech if s.strip()]
    present_parts = []
    for prefix in prefixes:
        suffix = safe_suffix([s[len(prefix):] for s in banned if s.startswith(prefix)])
        if suffix:
            present_parts.append(literal('"'+prefix)+' '+suffix)
    rules['present'] = ' | '.join((['('+social_expr+')'] if social_expr else []) + present_parts)
    question_bodies = [s[1:] for s in banned if s.startswith('¿')]
    if question_bodies:
        rules['question'] = literal('"¿')+' '+safe_suffix(question_bodies,True)
    serial = 0
    def compile(node):
        nonlocal serial
        if 'enum' in node:
            expr = ' | '.join(json_literal(v) for v in node['enum'])
            if not expr: raise ValueError('Empty enum cannot be constrained')
        elif 'oneOf' in node:
            expr = ' | '.join(compile(branch) for branch in node['oneOf'])
        elif node.get('type')=='string':
            pattern = node.get('pattern')
            if pattern and pattern.startswith('^¿'):
                return 'question'
            if pattern and pattern.startswith('^(Hola|'):
                return 'present'
            if pattern: raise ValueError('Unsupported string pattern')
            if 'maxLength' in node:
                maximum = node['maxLength']
                if type(maximum) is not int or not 0 <= maximum <= 32000:
                    raise ValueError('Unsupported string bound')
                serial += 1
                name = 's'+str(serial)
                rules[name] = r'"\"" char{0,'+str(maximum)+r'} "\"" ws'
                return name
            return 'string'
        elif node.get('type')=='object':
            properties = node.get('properties',{})
            if set(node.get('required',[]))!=set(properties) or node.get('additionalProperties') is not False:
                raise ValueError('Only exact required-field objects are supported')
            fields = []
            for key,value in properties.items():
                fields.append(json_literal(key)+' '+literal(':')+' ws '+compile(value))
            expr = literal('{')+' ws '+(' '+literal(',')+' ws ').join(fields)+' '+literal('}')+' ws'
        elif node.get('type')=='array':
            item = compile(node['items'])
            maximum = node.get('maxItems',8)
            minimum = node.get('minItems',0)
            if not 0<=minimum<=maximum<=32: raise ValueError('Unsupported array bound')
            variants = [' '.join([item]+[literal(',')+' ws '+item]*(n-1)) if n else '' for n in range(minimum,maximum+1)]
            expr = literal('[')+' ws ('+' | '.join(variants)+') '+literal(']')+' ws'
        else:
            raise ValueError('Unsupported schema type')
        serial += 1
        name = 'r'+str(serial)
        rules[name] = expr
        return name
    root = compile(schema)
    return 'root ::= ws '+root+'\n'+'\n'.join(name+' ::= '+expr for name,expr in rules.items())+'\n'
