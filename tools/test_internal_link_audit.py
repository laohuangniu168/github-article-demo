from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from article_spec import ArticleSpec
from internal_link_audit import audit_article, audit_batch
from internal_link_injector import InjectionResult
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


if __name__ == "__main__": unittest.main()
