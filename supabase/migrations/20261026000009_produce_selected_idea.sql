-- v2.6 (B1): make exactly the idea the owner selected.

-- A generated idea is turned into a research idea (with its stored sources) once; this links the two, so the
-- dashboard can show which package an idea became. Set by the engine only (owners can't update this column).
alter table public.generated_ideas
  add column content_idea_id uuid references public.content_ideas(id) on delete set null;
create unique index generated_ideas_content_idea_uidx on public.generated_ideas (content_idea_id)
  where content_idea_id is not null;

-- One package per research idea. Both the guided "Create package" and the weekly batch reuse an existing package
-- for an idea instead of making a second one, even if two requests arrive at the same time.
create unique index content_projects_one_per_idea on public.content_projects (idea_id)
  where idea_id is not null and parent_project_id is null;
