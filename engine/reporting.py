"""UI-free reporting definitions and detached, source-scoped report contexts.

The legacy builders share many implicit helpers. ``bind_context`` binds that
existing function graph to a private snapshot, rather than swapping live globals
or reimplementing grading policy. It exposes no Streamlit API or persistence API.
"""
from copy import deepcopy
from dataclasses import dataclass
from types import CodeType, FunctionType, SimpleNamespace
from uuid import UUID
import hashlib
import json

SORT_MODES = ('manual', 'last_first', 'first_last', 'gojuon', 'email')


def definition_issues(definitions):
    """Return structural issue codes only (never names, IDs or roster content)."""
    issues = []
    if not isinstance(definitions, list):
        return ['expected-list']
    ids, names = set(), set()
    for definition in definitions:
        if not isinstance(definition, dict):
            issues.append('expected-object')
            continue
        identifier, name = definition.get('id'), definition.get('name')
        try:
            UUID(identifier)
        except (ValueError, TypeError, AttributeError):
            issues.append('invalid-reporting-id')
        if isinstance(identifier, str):
            if identifier in ids:
                issues.append('duplicate-reporting-id')
            ids.add(identifier)
        if not isinstance(name, str) or not name.strip():
            issues.append('required-reporting-name')
        else:
            key = name.strip().casefold()
            if key in names:
                issues.append('duplicate-reporting-name')
            names.add(key)
        if definition.get('sort_mode') not in SORT_MODES:
            issues.append('invalid-reporting-sort')
        members = definition.get('members')
        if not isinstance(members, list):
            issues.append('expected-members-list')
            continue
        seen = set()
        for member in members:
            if not isinstance(member, dict) or set(member) != {'student_id', 'source_class'}:
                issues.append('invalid-reporting-member')
                continue
            if any(not isinstance(v, str) or not v.strip() for v in member.values()):
                issues.append('invalid-reporting-member')
                continue
            sid = member['student_id']
            if sid in seen:
                issues.append('duplicate-reporting-member')
            seen.add(sid)
        if set(definition) != {'id', 'name', 'sort_mode', 'members'}:
            issues.append('invalid-reporting-fields')
    return issues


@dataclass(frozen=True)
class ReportMember:
    student_id: str
    source_class: str


@dataclass(frozen=True)
class ReportScope:
    id: str
    name: str
    term: str
    members: tuple[ReportMember, ...]
    custom: bool = False


def resolve_members(definition, session, gradebook, sort_roster):
    """Resolve explicit references; preserve broken entries as blocking messages."""
    errors, entries = [], []
    classes = {c['name']: c for c in session['classes']}
    contexts = set()
    for member in definition['members']:
        sid, source = member['student_id'], member['source_class']
        label = f'{sid} ({source})'
        roster = session['rosters'].get(source, [])
        archived = session.get('archived_students', {}).get(source, [])
        row = next((r for r in roster if r.get('key') == sid), None)
        student = gradebook.students.get(sid)
        assignments = {a.name for a in gradebook.assignments if a.class_name == source}
        evidence_member = student and (any(sc.assignment in assignments
                          for bucket in student.scores.values() for sc in bucket)
                          or any(sid in a.draft_feedback for a in gradebook.assignments
                                 if a.class_name == source))
        if source not in classes or any(r.get('key') == sid for r in archived) or not (row or evidence_member):
            errors.append(f'{label}: unresolved or archived member; repair or remove this entry.')
            continue
        metadata = classes[source]
        contexts.add(tuple(str(metadata.get(k, '') or '').strip().casefold()
                           for k in ('subject', 'grade', 'myp_year')))
        # Scores carry assignment names, not source IDs. If this student belongs
        # to two groups with the same task title, choosing a source does not
        # establish which group owns their historical score.
        other_groups = {c for c, rows in session['rosters'].items()
                        if c != source and any(r.get('key') == sid for r in rows)}
        collisions = assignments & {a.name for a in gradebook.assignments
                                     if a.class_name in other_groups}
        if student and (any(sc.assignment in collisions for b in student.scores.values() for sc in b)
                        or collisions & set(student.exam_results)):
            errors.append(f'{label}: ambiguous legacy evidence shared by source groups.')
            continue
        entries.append(dict(row or {'key': sid, 'name': student.name}, source_class=source))
    if len(contexts) > 1:
        errors.append('Source groups have conflicting subject, school year level or MYP year. Resolve class settings first.')
    if definition['sort_mode'] != 'manual':
        entries = sort_roster(entries, definition['sort_mode'])
    return tuple(ReportMember(r['key'], r['source_class']) for r in entries), errors


def content_fingerprint(scope, session, gradebook):
    from dataclasses import asdict
    payload = {'scope': asdict(scope), 'session': session, 'gradebook': asdict(gradebook)}
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def source_snapshot(session, gradebook, scope, source):
    """Detach all evidence, select source members, and normalize copied flags."""
    from .models import Student
    state = deepcopy(session)
    book = deepcopy(gradebook)
    book.assignments = [a for a in book.assignments if a.class_name == source]
    names = {a.name for a in book.assignments}
    roster = state['rosters'].get(source, [])
    selected = [m.student_id for m in scope.members if m.source_class == source]
    students = {}
    for sid in selected:
        row = next((r for r in roster if r.get('key') == sid), {})
        student = book.students.get(sid) or Student(student_id=sid, name=row.get('name', ''))
        if row.get('name'):
            student.name = row['name']
        student.scores = {c: [sc for sc in bucket if sc.assignment in names]
                          for c, bucket in student.scores.items()}
        student.exam_results = {n: r for n, r in student.exam_results.items() if n in names}
        for bucket in student.scores.values():
            for score in bucket:
                assignment = next(a for a in book.assignments if a.name == score.assignment)
                score.include_in_report = bool(state.get('active_by_term', {}).get(scope.term, {}).get(
                    score.assignment, (assignment.term or scope.term) == scope.term)) and not assignment.is_draft and score.assignment not in state.get('archived', [])
        students[sid] = student
    book.students = students
    for a in book.assignments:
        a.draft_feedback = {sid: f for sid, f in a.draft_feedback.items() if sid in students}
    state.update(gradebook=book, active_class=source, active_term=scope.term,
                 roster=roster, unit_plan=state.get('unit_plans', {}).get(source),
                 active=state.get('active_by_term', {}).get(scope.term, {}),
                 llm_response=state.get('comments_by_term', {}).get(scope.term, {}),
                 report_name=scope.name if scope.custom else '')
    return state


def bind_context(namespace, state):
    """Bind the legacy read-only calculation/export call graph to detached data.

    No global replacement, ContextVar, live session access or Streamlit methods.
    Any accidental UI call fails closed. Callers retain the private state only
    for the lifetime of one export operation.
    """
    roots = ('_student_docx', 'build_excel_bytes', 'build_class_comments_docx',
             'calculation_method', 'student_term_grades', 'aggregate_with_policy',
             'student_email_for', 'gb', 'assignment_table', 'students_for_active_class')
    functions, references = {}, set()

    def code_names(code):
        result = set(code.co_names)
        for constant in code.co_consts:
            if isinstance(constant, CodeType):
                result.update(code_names(constant))
        return result

    def visit(name):
        value = namespace.get(name)
        references.add(name)
        if name in functions or not isinstance(value, FunctionType) or value.__globals__ is not namespace:
            return
        if value.__closure__:
            raise ValueError('Report helpers must not close over live state')
        functions[name] = value
        for dependency in code_names(value.__code__):
            visit(dependency)

    for root in roots:
        visit(root)
    bound = {name: namespace[name] for name in references if name in namespace}
    bound['__builtins__'] = namespace['__builtins__']
    bound['st'] = SimpleNamespace(session_state=state)
    for name, value in functions.items():
        clone = FunctionType(value.__code__, bound, value.__name__, value.__defaults__)
        clone.__kwdefaults__ = value.__kwdefaults__
        bound[name] = clone
    return SimpleNamespace(**bound)
