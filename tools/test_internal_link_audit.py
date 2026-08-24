from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from article_spec import ArticleSpec
from internal_link_audit import _scan_markdown, audit_article, audit_batch
from internal_link_injector import InjectionResult, Placement, SkippedTarget
from internal_link_registry import RegistryEntry, RegistrySnapshot, compute_registry_version
from internal_link_selector import LinkSelectionPlan, SelectedTarget


def entry(i=0, **kw):
    slug=kw.pop("slug",f"target-{i:02d}"); title=kw.pop("title",f"目标主题 {i:02d}")
    data=dict(slug=slug,title=title,cluster="content-seo",cluster_source="explicit",source_batch="production-batch-001.txt",markdown_path=f"articles/{slug}.md",relative_url=f"./{slug}.html",canonical_url=f"https://laohuangniu168.github.io/github-article-demo/articles/{slug}.html",published=True,eligible_as_target=True)
    data.update(kw); return RegistryEntry(**data)


def registry(n=30, entries=None):
    es=tuple(entries or [entry(i) for i in range(n)]); batches=("production-batch-001.txt",)
    return RegistrySnapshot(es,batches,"1",compute_registry_version(es,source_batches=batches))


def plan(r,count=20,reason=None,source="new-content-article",same=False):
    selected=tuple(SelectedTarget(e.slug,e.cluster,50,("same_cluster:+50",),"frozen_registry",same,0,1,f"{i:064x}") for i,e in enumerate(r.entries[:count]))
    return LinkSelectionPlan("batch-6",source,"content-seo",r.registry_version,"v1.1-default-1",30,selected,(),len(selected),sum(x.same_batch for x in selected),0.0,reason,"PASS")


def markdown(r,count=20,related=8):
    body=count-related
    paragraphs="\n\n".join(f"自然内容 [{r.entries[i].title}](./{r.entries[i].slug}.html)。" for i in range(body))
    rel="\n".join(f"- [{r.entries[i].title}](./{r.entries[i].slug}.html)" for i in range(body,count))
    return f'---\ntitle: "新文章"\n---\n\n# 新文章\n\n{{% raw %}}\n\n## 正文\n\n{paragraphs}\n\n## 相关阅读\n\n{rel}\n\n## 总结\n\n结束。\n\n{{% endraw %}}\n'


def plain_markdown(extra=""):
    return f'---\ntitle: "新文章"\n---\n\n# 新文章\n\n{{% raw %}}\n\n## 正文\n\n正文内容。{extra}\n\n## 总结\n\n结束。\n\n{{% endraw %}}\n'


def injection_result(r, count, *, requested=None, safe_shortfall=False, warnings=None):
    requested = count if requested is None else requested
    body = max(0, count - min(8, count))
    placements = tuple(
        Placement(
            r.entries[i].slug, r.entries[i].title, "title",
            "body" if i < body else "related", "正文" if i < body else "相关阅读",
            i, (0, 0), f"./{r.entries[i].slug}.html",
        )
        for i in range(count)
    )
    skipped = tuple(SkippedTarget(r.entries[i].slug, "NO_SAFE_INJECTION_POINT") for i in range(count, requested))
    if warnings is None:
        warnings = ("PLACEMENT_TARGET_NOT_MET", "INSUFFICIENT_SAFE_INJECTION_POINTS") if safe_shortfall else ()
    return InjectionResult(
        "new-content-article", "batch-6", r.registry_version, "v1.1-default-1",
        requested, body, count - body, skipped, placements, tuple(warnings), (),
        "PASS_WITH_SHORTFALL" if safe_shortfall else "PASS",
    )


class AuditTests(unittest.TestCase):
    def run_audit(self, text=None, r=None, p=None, source=None, **kw):
        r=r or registry(); source=source or ArticleSpec("new-content-article","内容优化文章","content-seo","explicit"); p=p or plan(r)
        return audit_article(text or markdown(r),source=source,plan=p,registry=r,registry_version=kw.pop("registry_version",r.registry_version),config_version=kw.pop("config_version","v1.1-default-1"),batch_id="batch-6",file_exists=kw.pop("file_exists",lambda _:True),**kw)

    def test_01_normal_pass(self): self.assertEqual(self.run_audit().final_status,"PASS")
    def test_02_shortfall(self):
        r=registry(); p=plan(r,5,"INSUFFICIENT_RELEVANT_CANDIDATES"); self.assertEqual(self.run_audit(markdown(r,5,4),r,p).final_status,"PASS_WITH_SHORTFALL")
    def mutated(self, old, new, **kw): return self.run_audit(markdown(registry()).replace(old,new),**kw)
    def test_03_self(self): self.assertEqual(self.mutated("./target-00.html","./new-content-article.html").final_status,"FAIL")
    def test_04_duplicate(self): self.assertGreater(self.mutated("./target-01.html","./target-00.html").duplicate_targets,0)
    def test_05_body_related_duplicate(self): self.assertGreater(self.mutated("./target-12.html","./target-00.html").duplicate_targets,0)
    def test_06_out_registry(self): self.assertGreater(self.mutated("./target-00.html","./unknown-target.html").out_of_registry_targets,0)
    def test_07_ineligible(self):
        r=registry(entries=[entry(0,eligible_as_target=False)]+[entry(i) for i in range(1,30)]); self.assertGreater(self.run_audit(markdown(r),r,plan(r)).invalid_targets,0)
    def test_08_missing_file(self): self.assertGreater(self.run_audit(file_exists=lambda p:not p.endswith("target-00.md")).broken_targets,0)
    def test_09_parent_url(self): self.assertGreater(self.mutated("./target-00.html","../target-00.html").invalid_targets,0)
    def test_10_absolute_url(self): self.assertGreater(self.mutated("./target-00.html","https://example.com/target-00.html").invalid_targets,0)
    def test_11_query(self): self.assertGreater(self.mutated("./target-00.html","./target-00.html?x=1").invalid_targets,0)
    def test_12_fragment(self): self.assertGreater(self.mutated("./target-00.html","./target-00.html#x").invalid_targets,0)
    def zone(self, fragment, field):
        r=registry(); text=markdown(r).replace("title: \"新文章\"",f'title: "新文章 {fragment}"'); return getattr(self.run_audit(text,r,plan(r)),field)
    def test_13_front(self): self.assertGreater(self.zone("[目标](./target-00.html)","front_matter_injections"),0)
    def test_14_h1(self): self.assertGreater(self.run_audit(markdown(registry()).replace("# 新文章","# [新文章](./target-00.html)")).front_matter_injections,0)
    def inject_zone(self, fragment, field):
        r=registry(); text=markdown(r).replace("## 正文",f"## 正文\n\n{fragment}"); return getattr(self.run_audit(text,r,plan(r)),field)
    def test_15_fence(self): self.assertGreater(self.inject_zone("```\n[x](./target-00.html)\n```","code_block_injections"),0)
    def test_16_inline(self): self.assertGreater(self.inject_zone("`[x](./target-00.html)`","inline_code_injections"),0)
    def test_17_liquid(self): self.assertGreater(self.inject_zone("{% if [x](./target-00.html) %}","liquid_injections"),0)
    def test_18_raw_line(self): self.assertGreater(self.inject_zone("{% raw [x](./target-00.html) %}","liquid_injections"),0)
    def test_19_html_attr(self): self.assertGreater(self.inject_zone('<a href="[x](./target-00.html)">x</a>',"html_attribute_injections"),0)
    def test_20_html_comment(self): self.assertGreater(self.inject_zone("<!-- [x](./target-00.html) -->","html_comment_injections"),0)
    def test_21_malformed(self): self.assertGreater(self.mutated("[目标主题 00](./target-00.html)","[目标主题 00](./target-00.html").malformed_markdown_links,0)
    def test_22_anchor_duplicate(self): self.assertGreater(self.mutated("目标主题 01","目标主题 00").anchor_duplicates,0)
    def test_23_anchor_length(self): self.assertEqual(self.mutated("目标主题 00","x").final_status,"FAIL")
    def test_24_over_max(self):
        r=registry(31); self.assertEqual(self.run_audit(markdown(r,31,10),r,plan(r,31)).final_status,"FAIL")
    def test_25_bad_shortfall(self):
        r=registry(); self.assertEqual(self.run_audit(markdown(r,5,4),r,plan(r,5,"OTHER")).final_status,"FAIL")
    def test_26_registry_version(self): self.assertEqual(self.run_audit(registry_version="bad").final_status,"FAIL")
    def test_27_config_version(self): self.assertEqual(self.run_audit(config_version="bad").final_status,"FAIL")
    def test_28_relevance(self):
        r=registry(entries=[entry(i,cluster="technical-seo") for i in range(30)]); self.assertEqual(self.run_audit(markdown(r),r,plan(r)).final_status,"FAIL")
    def test_29_not_planned(self):
        r=registry(); self.assertEqual(self.run_audit(markdown(r),r,plan(r,19)).final_status,"FAIL")
    def test_30_same_batch_cap(self):
        r=registry(); p=plan(r,20,same=True); self.assertEqual(self.run_audit(markdown(r),r,p).final_status,"FAIL")
    def test_31_inbound_cap(self):
        rs=[replace(self.run_audit(),article_slug=f"s{i}") for i in range(3)]; self.assertEqual(audit_batch(rs,{f"s{i}":["target-00"] for i in range(3)}).final_status,"FAIL")
    def test_32_related_over_10(self):
        r=registry(31); self.assertEqual(self.run_audit(markdown(r,20,11),r,plan(r,20)).final_status,"FAIL")
    def test_33_multiple_related(self): self.assertEqual(self.run_audit(markdown(registry()).replace("## 总结","## 相关阅读\n\n## 总结")).final_status,"FAIL")
    def test_34_related_malformed(self): self.assertEqual(self.run_audit(markdown(registry()).replace("## 总结","普通文字\n\n## 总结")).final_status,"FAIL")
    def test_35_counts(self):
        x=self.run_audit(); self.assertEqual((x.body_links,x.related_links),(12,8))
    def test_36_zero_links(self):
        r=registry(); p=plan(r,0,"INSUFFICIENT_RELEVANT_CANDIDATES"); self.assertEqual(self.run_audit(markdown(r,0,0),r,p).final_status,"PASS_WITH_SHORTFALL")
    def test_37_batch_aggregation(self):
        x=self.run_audit(); b=audit_batch([x,x],{"s1":["a"],"s2":["a"]}); self.assertEqual(b.inbound_cap,2)
    def test_38_deterministic(self): self.assertEqual(self.run_audit(),self.run_audit())
    def test_39_mutation_detection(self): self.assertEqual(self.run_audit(protected_hashes={"a":"1"},current_hashes={"a":"2"}).final_status,"FAIL")
    def test_40_frozen_hash_match(self): self.assertNotEqual(Path(__file__).read_bytes(),b"")

    def test_41_safe_point_shortfall_from_injection_evidence(self):
        r=registry(); p=plan(r,25); ir=injection_result(r,17,requested=25,safe_shortfall=True)
        x=self.run_audit(markdown(r,17,8),r,p,injection_result=ir)
        self.assertEqual((x.final_status,x.shortfall_reason),("PASS_WITH_SHORTFALL","INSUFFICIENT_SAFE_INJECTION_POINTS"))

    def test_42_relevance_selection_shortfall(self):
        r=registry(); p=plan(r,12,"INSUFFICIENT_RELEVANT_CANDIDATES")
        self.assertEqual(self.run_audit(markdown(r,12,8),r,p,injection_result=injection_result(r,12)).shortfall_reason,"INSUFFICIENT_RELEVANT_CANDIDATES")

    def test_43_inbound_selection_shortfall(self):
        r=registry(); p=plan(r,12,"INBOUND_CAP_EXHAUSTED")
        self.assertEqual(self.run_audit(markdown(r,12,8),r,p,injection_result=injection_result(r,12)).shortfall_reason,"INBOUND_CAP_EXHAUSTED")

    def test_44_fake_safe_point_evidence_fails(self):
        r=registry(); p=plan(r,25); ir=injection_result(r,17,requested=25,safe_shortfall=True)
        ir=replace(ir,skipped_targets=())
        self.assertEqual(self.run_audit(markdown(r,17,8),r,p,injection_result=ir).final_status,"FAIL")

    def test_45_illegal_injection_warning_fails(self):
        r=registry(); p=plan(r,25); ir=injection_result(r,17,requested=25,safe_shortfall=True,warnings=("MADE_UP_REASON",))
        self.assertEqual(self.run_audit(markdown(r,17,8),r,p,injection_result=ir).final_status,"FAIL")

    def test_46_actual_at_least_minimum_ignores_shortfall_warning(self):
        r=registry(); ir=injection_result(r,20,requested=25,safe_shortfall=True)
        x=self.run_audit(markdown(r,20,8),r,plan(r,25),injection_result=ir)
        self.assertEqual((x.final_status,x.shortfall_reason),("PASS",None))

    def provenance_case(self, baseline, final, count=20, ir=None):
        r=registry(); ir=ir or injection_result(r,count)
        return self.run_audit(final,r,plan(r,count),injection_result=ir,pre_injection_markdown=baseline)

    def test_47_pre_existing_root_and_external_links_preserved(self):
        r=registry(); baseline=plain_markdown(" [旧站内](/legacy/) 与 [外部](https://example.com/x)")
        final=markdown(r,20,8).replace("## 正文", "## 正文\n\n正文内容 [旧站内](/legacy/) 与 [外部](https://example.com/x)")
        x=self.provenance_case(baseline,final)
        self.assertEqual((x.final_status,x.pre_existing_links,x.invalid_targets),("PASS",2,0))

    def test_48_pre_existing_link_mutation_fails(self):
        r=registry(); baseline=plain_markdown(" [旧站内](/legacy/)")
        final=markdown(r,20,8).replace("## 正文","## 正文\n\n正文内容 [旧站内](/changed/)")
        self.assertEqual(self.provenance_case(baseline,final).final_status,"FAIL")

    def test_49_new_root_or_external_link_fails(self):
        r=registry(); baseline=plain_markdown(); ir=injection_result(r,20)
        for url in ("/new-root/","https://example.com/new"):
            final=markdown(r,20,8).replace("## 正文",f"## 正文\n\n[新链接]({url})")
            bad=replace(ir,placements=ir.placements+(Placement("new-link","新链接","title","body","正文",99,(0,0),url),),body_links=ir.body_links+1,requested_targets=ir.requested_targets+1)
            self.assertEqual(self.provenance_case(baseline,final,20,bad).final_status,"FAIL")

    def test_50_new_strict_link_outside_registry_fails(self):
        r=registry(); baseline=plain_markdown(); url="./unknown-target.html"
        final=markdown(r,20,8).replace("## 正文",f"## 正文\n\n[未知目标]({url})")
        ir=injection_result(r,20); bad=replace(ir,placements=ir.placements+(Placement("unknown-target","未知目标","title","body","正文",99,(0,0),url),),body_links=ir.body_links+1,requested_targets=21)
        self.assertEqual(self.provenance_case(baseline,final,20,bad).final_status,"FAIL")

    def test_51_new_valid_strict_link_with_placement_passes(self):
        r=registry(); baseline=plain_markdown(); final=markdown(r,20,8)
        x=self.provenance_case(baseline,final,20,injection_result(r,20))
        self.assertEqual((x.final_status,x.internal_links,x.pre_existing_links),("PASS",20,0))

    def test_52_nested_link_attack_fails(self):
        r=registry(); baseline=plain_markdown(); final=markdown(r,20,8).replace("## 正文","## 正文\n\n[外层 [内层](./target-00.html)](./target-01.html)")
        self.assertEqual(self.provenance_case(baseline,final).final_status,"FAIL")

    def test_53_missing_injected_link_fails(self):
        r=registry(); baseline=plain_markdown(); final=markdown(r,19,8)
        self.assertEqual(self.provenance_case(baseline,final,20,injection_result(r,20)).final_status,"FAIL")

    def test_54_duplicate_injected_target_mixed_with_pre_existing(self):
        r=registry(); baseline=plain_markdown(" [旧链接](./target-19.html)")
        final=markdown(r,20,8).replace("## 正文","## 正文\n\n正文内容 [旧链接](./target-19.html)")
        x=self.provenance_case(baseline,final,20,injection_result(r,20))
        self.assertEqual((x.final_status,x.internal_links,x.pre_existing_links),("PASS",20,1))

    def test_55_gate7_failure_site_minimal_read_only_reproduction(self):
        r=registry(); invalid_shortfall=invalid_url=0
        for count in (10,12,14,16,17,19):
            p=plan(r,24); ir=injection_result(r,count,requested=24,safe_shortfall=True)
            result=self.run_audit(markdown(r,count,min(8,count)),r,p,injection_result=ir)
            self.assertEqual(result.final_status,"PASS_WITH_SHORTFALL")
            invalid_shortfall += sum(e.code == "INVALID_SHORTFALL_REASON" for e in result.events)
        baseline=plain_markdown(" [Canonical 标签](/canonical-guide/)")
        final=markdown(r,20,8).replace("## 正文","## 正文\n\n[Canonical 标签](/canonical-guide/)")
        canonical=self.provenance_case(baseline,final,20,injection_result(r,20))
        invalid_url += sum(e.code == "INVALID_INTERNAL_URL" for e in canonical.events)
        self.assertEqual((canonical.final_status,canonical.pre_existing_links),("PASS",1))
        self.assertIn("[Canonical 标签](/canonical-guide/)",baseline)
        self.assertIn("[Canonical 标签](/canonical-guide/)",final)
        self.assertEqual((invalid_shortfall,invalid_url),(0,0))

    def test_56_fenced_log_html_is_not_malformed(self):
        text=plain_markdown().replace("正文内容。","```log\n123 - [18/Mar/2025] GET /article/123.html\n```\n\n正文内容。")
        _, malformed, _, _=_scan_markdown(text)
        self.assertEqual(malformed,0)

    def test_57_normal_paragraph_malformed_still_fails(self):
        r=registry(); text=markdown(r).replace("## 正文","## 正文\n\n[broken ./target-00.html")
        x=self.run_audit(text,r,plan(r))
        self.assertEqual(x.final_status,"FAIL")
        self.assertTrue(any(e.code=="MALFORMED_MARKDOWN_LINK" for e in x.events))

    def test_58_inline_code_markdown_looking_text_is_ignored(self):
        r=registry(); fragment="`[foo](/bar)`"
        baseline=plain_markdown(fragment)
        final=markdown(r,20,8).replace("## 正文",f"## 正文\n\n{fragment}")
        x=self.provenance_case(baseline,final,20,injection_result(r,20))
        self.assertEqual((x.final_status,x.malformed_markdown_links),("PASS",0))

    def test_59_fenced_markdown_looking_text_is_ignored(self):
        sample="```text\n[abc]\n(foo)\n/article/123.html\n[abc](/foo)\n![image](/foo.png)\n```"
        r=registry(); baseline=plain_markdown().replace("正文内容。",sample)
        final=markdown(r,20,8).replace("## 正文",f"## 正文\n\n{sample}")
        x=self.provenance_case(baseline,final,20,injection_result(r,20))
        self.assertEqual((x.final_status,x.internal_links,x.malformed_markdown_links,x.code_block_injections),("PASS",20,0,0))

    def test_60_real_fenced_code_mutation_still_fails(self):
        r=registry(); before_fence="```log\nGET /article/123.html\n```"; after_fence="```log\nGET /article/456.html\n```"
        baseline=plain_markdown().replace("正文内容。",before_fence)
        final=markdown(r,20,8).replace("## 正文",f"## 正文\n\n{after_fence}")
        x=self.provenance_case(baseline,final,20,injection_result(r,20))
        self.assertEqual(x.final_status,"FAIL")
        self.assertTrue(any(e.code=="PROTECTED_ZONE_VIOLATION" for e in x.events))

    def test_61_real_inline_code_mutation_still_fails(self):
        r=registry(); baseline=plain_markdown(" `[foo](/bar)`")
        final=markdown(r,20,8).replace("## 正文","## 正文\n\n`[foo](/changed)`")
        x=self.provenance_case(baseline,final,20,injection_result(r,20))
        self.assertEqual(x.final_status,"FAIL")
        self.assertTrue(any(e.code=="PROTECTED_ZONE_VIOLATION" for e in x.events))


if __name__ == "__main__": unittest.main()
