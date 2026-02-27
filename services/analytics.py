import json
import logging
import random
from collections import defaultdict
from typing import List, Dict, Any
from core.database import db
from core.config import OBSIDIAN_INBOX

logger = logging.getLogger(__name__)

class AnalyticsService:
    def __init__(self):
        self.db = db

    def export_coauthor_canvas(self) -> Dict[str, Any]:
        """
        Generates an Obsidian .canvas file for the co-author network.
        """
        data = self.get_coauthor_network()
        canvas = {"nodes": [], "edges": []}
        
        def get_pos(name):
            random.seed(name)
            return random.randint(-1500, 1500), random.randint(-1500, 1500)

        active_nodes = [n for n in data['nodes'] if n['count'] > 1]
        
        for i, node in enumerate(active_nodes):
            x, y = get_pos(node['id'])
            canvas["nodes"].append({
                "id": f"author_{i}",
                "type": "text",
                "text": f"### {node['name']}\n{node['count']} books in library",
                "x": x, "y": y, "width": 250, "height": 100
            })
            node["canvas_id"] = f"author_{i}"

        name_to_id = {n['id']: n['canvas_id'] for n in active_nodes}
        
        edge_count = 0
        for link in data['links']:
            if link['source'] in name_to_id and link['target'] in name_to_id:
                canvas["edges"].append({
                    "id": f"edge_{edge_count}",
                    "fromNode": name_to_id[link['source']],
                    "toNode": name_to_id[link['target']],
                    "label": f"{link['value']} collaborations"
                })
                edge_count += 1

        output_path = OBSIDIAN_INBOX / "Co-Author Network.canvas"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(canvas, f, indent=2)
            
        return {"success": True, "path": str(output_path)}

    def get_coauthor_network(self) -> Dict[str, Any]:
        """
        Extracts a node-link network of authors with robust parsing and normalization.
        Uses high-quality strings from zbmath_cache and the zbMATH API for disambiguation.
        """
        from services.zbmath import zbmath_service
        
        with self.db.get_connection() as conn:
            # 1. Fetch all books with their Zbl IDs and authors
            books = conn.execute("""
                SELECT b.id, b.zbl_id, b.author, z.authors as zb_authors 
                FROM books b
                LEFT JOIN zbmath_cache z ON b.zbl_id = z.zbl_id
                WHERE b.author IS NOT NULL AND b.author != 'Unknown'
            """).fetchall()

        canonical_to_name = {}
        author_counts = defaultdict(int)
        links = defaultdict(int)

        def normalize_name(name):
            if not name: return "", ""
            name = name.strip()
            # Handle 'Last, First'
            if ',' in name:
                parts = name.split(',')
                if len(parts) == 2:
                    name = f"{parts[1].strip()} {parts[0].strip()}"
            
            name = name.replace('.', '').replace('  ', ' ').strip()
            parts = name.split()
            if len(parts) >= 2:
                canonical = f"{parts[-1]} {parts[0][0]}".upper()
            else:
                canonical = name.upper()
            return name, canonical

        for book in books:
            # Prefer zbmath authors if available
            if book['zb_authors']:
                try:
                    author_list = json.loads(book['zb_authors'])
                except:
                    author_list = self.parse_author_string(book['author'])
            else:
                author_list = self.parse_author_string(book['author'])
            
            processed_canons = []
            for a in author_list:
                clean_a = a.strip().strip(',').strip()
                if not clean_a or len(clean_a) < 3 or clean_a.lower() in ['unknown', 'none', 'n/a', 'various']: continue
                
                disp_name, canon_id = normalize_name(clean_a)
                if len(canon_id) < 3: continue
                
                processed_canons.append(canon_id)
                author_counts[canon_id] += 1
                if canon_id not in canonical_to_name or len(disp_name) > len(canonical_to_name[canon_id]):
                    canonical_to_name[canon_id] = disp_name
            
            # Create links
            if len(processed_canons) > 1:
                unique_canons = sorted(list(set(processed_canons)))
                for i in range(len(unique_canons)):
                    for j in range(i + 1, len(unique_canons)):
                        links[(unique_canons[i], unique_canons[j])] += 1

        formatted_nodes = [{"id": c, "name": canonical_to_name[c], "count": count} for c, count in author_counts.items()]
        formatted_links = [{"source": p[0], "target": p[1], "value": w} for p, w in links.items()]
        
        # Performance: Limit to nodes with at least 2 books OR at least one connection
        filtered_nodes = [n for n in formatted_nodes if n['count'] > 1 or any(l['source'] == n['id'] or l['target'] == n['id'] for l in formatted_links)]
        
        return {"nodes": filtered_nodes, "links": formatted_links}

    def parse_author_string(self, s):
        if not s: return []
        if ';' in s: return [a.strip() for a in s.split(';')]
        if ' & ' in s: return [a.strip() for a in s.split(' & ')]
        if ' and ' in s.lower(): return [a.strip() for a in s.replace(' and ', ' & ').replace(' AND ', ' & ').split(' & ')]
        raw_parts = [a.strip() for a in s.split(',')]
        if len(raw_parts) > 2 and len(raw_parts) % 2 == 0:
            return [f"{raw_parts[i+1]} {raw_parts[i]}" for i in range(0, len(raw_parts), 2)]
        return raw_parts

    def get_msc_timeline(self) -> Dict[str, Any]:
        """
        Aggregates books by decade and broad thematic categories.
        """
        MSC_MAP = {
            "00": "General/History", "01": "General/History", "03": "Logic/Foundations", "04": "Logic/Foundations",
            "05": "Combinatorics", "06": "Algebra", "08": "Algebra", "11": "Number Theory", "12": "Algebra", "13": "Algebra", 
            "14": "Algebraic Geometry", "15": "Algebra", "16": "Algebra", "17": "Algebra", "18": "Algebra", "19": "K-Theory",
            "20": "Group Theory", "22": "Lie Groups", "26": "Analysis", "28": "Analysis", "30": "Complex Analysis",
            "31": "Analysis", "32": "Complex Analysis", "33": "Special Functions", "34": "Differential Equations", "35": "Differential Equations",
            "37": "Dynamical Systems", "39": "Analysis", "40": "Analysis", "41": "Analysis", "42": "Harmonic Analysis", "43": "Harmonic Analysis",
            "44": "Analysis", "45": "Analysis", "46": "Functional Analysis", "47": "Operator Theory", "49": "Calculus of Variations",
            "51": "Geometry", "52": "Geometry", "53": "Differential Geometry", "54": "Topology", "55": "Algebraic Topology", "57": "Topology", "58": "Global Analysis",
            "60": "Probability", "62": "Statistics", "65": "Numerical Analysis", "68": "Computer Science", "70": "Math Physics", "74": "Math Physics",
            "76": "Math Physics", "78": "Math Physics", "80": "Math Physics", "81": "Quantum Theory", "82": "Statistical Mechanics", "83": "Relativity",
            "85": "Math Physics", "86": "Math Physics", "90": "Optimization", "91": "Game Theory", "92": "Applied Math", "93": "Systems Theory",
            "94": "Information Theory", "97": "Education"
        }
        # Reverse map for click-to-search (Broad Cat -> List of Top-level MSC codes)
        CAT_TO_MSC = defaultdict(list)
        for msc, cat in MSC_MAP.items(): CAT_TO_MSC[cat].append(msc)

        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT year, msc_class FROM books WHERE year IS NOT NULL AND year > 1850 AND year <= 2025 ORDER BY year ASC").fetchall()

        data = defaultdict(lambda: defaultdict(int))
        categories = set()
        for row in rows:
            decade_str = f"{(row['year'] // 10) * 10}s"
            msc_val = row['msc_class']
            cat_name = MSC_MAP.get(msc_val.split(',')[0].strip()[:2], "Other") if msc_val else "Other"
            data[decade_str][cat_name] += 1
            categories.add(cat_name)

        decades = sorted(data.keys())
        sorted_categories = sorted(list(categories))
        datasets = [{"label": cat, "data": [data[d][cat] for d in decades], "msc_codes": CAT_TO_MSC.get(cat, [])} for cat in sorted_categories]

        milestones = [
            {"year": "1900s", "event": "Hilbert's 23 Problems"}, {"year": "1930s", "event": "Gödel's Incompleteness"},
            {"year": "1950s", "event": "Bourbaki / Category Theory"}, {"year": "1970s", "event": "Chaos Theory / Solitons"},
            {"year": "1990s", "event": "Fermat's Last Theorem proved"}, {"year": "2000s", "event": "Poincaré Conjecture proved"}
        ]
        return {"labels": decades, "datasets": datasets, "milestones": milestones}

    def get_cross_pollination(self) -> Dict[str, Any]:
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT author, msc_class FROM books WHERE author IS NOT NULL AND msc_class IS NOT NULL AND author != 'Unknown'").fetchall()
        author_msc = defaultdict(set)
        for row in rows:
            msc_list = [m.strip()[:2] for m in row['msc_class'].split(',') if m.strip()[:2].isdigit()]
            authors = self.parse_author_string(row['author'])
            for author in authors:
                author = author.strip().strip(',').replace('.', '').strip()
                if not author or len(author) < 3 or author.lower() in ['unknown', 'none', 'n/a', 'various']: continue
                for msc in msc_list: author_msc[author].add(msc)
        bridge_authors = [{"author": a, "categories": sorted(list(mscs)), "count": len(mscs)} for a, mscs in author_msc.items() if len(mscs) > 1]
        bridge_authors.sort(key=lambda x: x['count'], reverse=True)
        return {"bridges": bridge_authors[:50]}

analytics_service = AnalyticsService()
