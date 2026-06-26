import os
import uuid
import pandas as pd
import matplotlib
# Use Agg backend for headless rendering without GUI window
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def render_vega_to_png(vega_config: dict, fallback_data: list = None, output_dir: str = "tmp_charts") -> str:
    """
    Parses a Vega-Lite chart configuration from BQCA, plots it using Matplotlib with a premium aesthetic,
    saves it to a temporary file, and returns the absolute path of the generated PNG.
    Supports both vertical and horizontal layouts, automatically cleans null values, and parses formatted strings.
    """
    # 1. Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    # 2. Extract data values
    values = vega_config.get("data", {}).get("values", [])
    if not values:
        values = fallback_data
        
    if not values:
        raise ValueError("No chart data values found in vega_config or fallback_data.")
        
    # Convert to pandas DataFrame
    df = pd.DataFrame(values)
    
    # 3. Extract encoding metadata
    x_encoding = vega_config.get("encoding", {}).get("x", {})
    y_encoding = vega_config.get("encoding", {}).get("y", {})
    
    x_field = x_encoding.get("field")
    y_field = y_encoding.get("field")
    
    if not x_field or not y_field:
        raise ValueError("X or Y encoding fields are missing in vega_config.")
        
    x_title = x_encoding.get("title", x_field).replace("_", " ").title()
    y_title = y_encoding.get("title", y_field).replace("_", " ").title()
    chart_title = vega_config.get("title", "Data Insights").replace("_", " ").title()
    mark = vega_config.get("mark", "bar")
    
    # 4. Detect Chart Orientation & Determine Categorical vs Numeric Axes
    x_type = x_encoding.get("type", "nominal")
    y_type = y_encoding.get("type", "quantitative")
    
    # In Vega-Lite: x=quantitative & y=nominal/ordinal indicates a horizontal chart
    is_horizontal = (x_type == "quantitative" and y_type in ("nominal", "ordinal"))
    
    if is_horizontal:
        cat_field = y_field
        num_field = x_field
        cat_title = y_title
        num_title = x_title
    else:
        cat_field = x_field
        num_field = y_field
        cat_title = x_title
        num_title = y_title
        
    # 5. Data Cleaning
    # Clean Categorical Axis: fill None/NaN with "N/A" and convert to string to prevent Matplotlib float crashes
    df[cat_field] = df[cat_field].fillna("N/A").astype(str)
    
    # Clean Numeric Axis: handle raw numbers as well as formatted string numbers containing commas
    if df[num_field].dtype == object:
        df[num_field] = df[num_field].astype(str).str.replace(",", "").str.strip()
    df[num_field] = pd.to_numeric(df[num_field], errors='coerce').fillna(0.0)
    
    # 6. Initialize Plot with clean, premium styling
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=300)
    ax.set_facecolor("#ffffff")
    fig.patch.set_facecolor("#ffffff")
    
    brand_color = "#4f46e5"  # Indigo
    grid_color = "#f1f5f9"   # Very light grey
    border_color = "#cbd5e1" # Slate grey
    
    # Helper for formatting values on labels
    def format_val(val):
        if val >= 1_000_000_000:
            return f"${val/1_000_000_000:.2f}B"
        elif val >= 1_000_000:
            return f"${val/1_000_000:.2f}M"
        elif val >= 1_000:
            return f"${val/1_000:.1f}K"
        else:
            return f"${val:.2f}"

    # 7. Plot based on chart type (mark) and orientation
    if mark == "bar":
        if is_horizontal:
            # Draw horizontal bars
            bars = ax.barh(df[cat_field], df[num_field], color=brand_color, height=0.6, edgecolor=None, alpha=0.9)
            # Invert y-axis if sorted descending in vega_config
            sort_y = y_encoding.get("sort", "")
            if isinstance(sort_y, str) and sort_y.startswith("-"):
                ax.invert_yaxis()
                
            # Add values to the right of bars if there are fewer than 12 categories
            if len(df) <= 12:
                for bar in bars:
                    width = bar.get_width()
                    label = format_val(width)
                    ax.annotate(label,
                                xy=(width, bar.get_y() + bar.get_height() / 2),
                                xytext=(5, 0),  # 5 points horizontal offset
                                textcoords="offset points",
                                ha='left', va='center', fontsize=7, color="#475569", fontweight='bold')
        else:
            # Draw vertical bars
            bars = ax.bar(df[cat_field], df[num_field], color=brand_color, width=0.6, edgecolor=None, alpha=0.9)
            # Add values on top of bars
            if len(df) <= 10:
                for bar in bars:
                    height = bar.get_height()
                    label = format_val(height)
                    ax.annotate(label,
                                xy=(bar.get_x() + bar.get_width() / 2, height),
                                xytext=(0, 3),  # 3 points vertical offset
                                textcoords="offset points",
                                ha='center', va='bottom', fontsize=7, color="#475569", fontweight='bold')
    elif mark == "line":
        if is_horizontal:
            ax.plot(df[num_field], df[cat_field], color=brand_color, marker='o', linewidth=2.5, markersize=5, alpha=0.9)
            sort_y = y_encoding.get("sort", "")
            if isinstance(sort_y, str) and sort_y.startswith("-"):
                ax.invert_yaxis()
        else:
            ax.plot(df[cat_field], df[num_field], color=brand_color, marker='o', linewidth=2.5, markersize=5, alpha=0.9)
    else:
        # Fallback
        if is_horizontal:
            ax.barh(df[cat_field], df[num_field], color=brand_color, height=0.6, alpha=0.9)
        else:
            ax.bar(df[cat_field], df[num_field], color=brand_color, width=0.6, alpha=0.9)
            
    # 8. Apply Premium Axis and Grid Styling
    ax.set_title(chart_title, fontsize=11, fontweight="bold", pad=15, color="#1e293b", loc="left")
    ax.set_xlabel(num_title if is_horizontal else cat_title, fontsize=8, fontweight="bold", labelpad=8, color="#475569")
    ax.set_ylabel(cat_title if is_horizontal else num_title, fontsize=8, fontweight="bold", labelpad=8, color="#475569")
    
    # Tick labels styling
    ax.tick_params(colors="#64748b", labelsize=8)
    
    # Rotate x labels if they are long/numerous (only relevant for vertical charts)
    if not is_horizontal:
        if len(df) > 5 or df[cat_field].map(len).max() > 6:
            plt.xticks(rotation=30, ha="right")
            
    # Remove top and right spines/borders
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(border_color)
    ax.spines['bottom'].set_color(border_color)
    
    # Add grid lines for readability
    if is_horizontal:
        ax.xaxis.grid(True, linestyle='-', linewidth=0.8, color=grid_color)
        ax.yaxis.grid(False)
        # Add slight padding to x-axis right limit for labels
        xlim_max = ax.get_xlim()[1]
        ax.set_xlim(0, xlim_max * 1.15)
    else:
        ax.yaxis.grid(True, linestyle='-', linewidth=0.8, color=grid_color)
        ax.xaxis.grid(False)
        # Add slight padding to y-axis top limit for labels
        ylim_max = ax.get_ylim()[1]
        ax.set_ylim(0, ylim_max * 1.15)
        
    # 9. Save to file
    filename = f"chart_{uuid.uuid4().hex[:8]}.png"
    file_path = os.path.abspath(os.path.join(output_dir, filename))
    
    plt.tight_layout()
    plt.savefig(file_path, facecolor=fig.get_facecolor(), edgecolor='none', bbox_inches='tight')
    plt.close(fig)
    
    print(f"Chart rendered successfully to: {file_path}")
    return file_path

# Quick local test
if __name__ == "__main__":
    test_vega = {
        "title": "November Sales by Year",
        "mark": "bar",
        "encoding": {
            "x": {"field": "d_year", "title": "Year"},
            "y": {"field": "total_sales", "title": "Total Sales ($)"}
        }
    }
    test_data = [
        {"d_year": 1998, "total_sales": 165087098.2},
        {"d_year": 1999, "total_sales": 160608947.5},
        {"d_year": 2000, "total_sales": 166033797.8},
        {"d_year": 2001, "total_sales": 161926008.5},
        {"d_year": 2002, "total_sales": 164861864.5}
    ]
    path = render_vega_to_png(test_vega, test_data)
    print("Generated test image at:", path)
